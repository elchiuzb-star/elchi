package uz.elchi.app.feature.client

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import androidx.core.net.toUri
import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.BuildConfig
import uz.elchi.app.R
import uz.elchi.app.api.generated.PromoBucketDTO
import uz.elchi.app.api.generated.ReferralCodeDTO
import uz.elchi.app.i18n.AppLocale
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.session.Session
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.CheckRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiDialog
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ItemLine
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.ListRowStyle
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.Segmented
import uz.elchi.app.ui.components.SkeletonCard
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.ThemeMode
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

// -- shared blocks ------------------------------------------------------------------------------------------------

/**
 * The prototype's `stat` tiles: small label over a big value, three in a row. With [selected] and [onSelect] they
 * are the settings' theme choice (the chosen tile outlined in brand, a radio for TalkBack).
 */
@Composable
internal fun <T> StatTiles(items: List<Triple<T, String, String>>, selected: T? = null, onSelect: ((T) -> Unit)? = null, compact: Boolean = false) {
    val c = Elchi.colors
    // Equal heights even when a label wraps ("Как на устройстве").
    Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items.forEach { (value, label, big) ->
            val active = onSelect != null && value == selected
            val shape = RoundedCornerShape(18.dp)
            Column(
                Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .heightIn(min = 64.dp)
                    .shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
                    .clip(shape)
                    .background(if (active) c.highlight else c.card)
                    .then(if (active) Modifier.border(2.dp, c.brand, shape) else Modifier)
                    .then(if (onSelect != null) Modifier.selectable(active, role = Role.RadioButton) { onSelect(value) } else Modifier)
                    .padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Text(label, style = Elchi.type.caption, color = c.muted, maxLines = 2)
                // [compact]: words, not numbers ("Tasdiqlangan") - a smaller size so a whole word fits a third of the row.
                Text(big, style = Elchi.type.section.copy(fontSize = if (compact) 14.sp else 18.sp, fontWeight = FontWeight.SemiBold, lineHeight = 23.sp), color = c.text, maxLines = 1)
            }
        }
    }
}

/** The prototype's `avatar`: initials (or the person icon) in a soft circle, name, phone, badges. */
@Composable
private fun AvatarCard(name: String?, phone: String, badge: String) {
    val c = Elchi.colors
    ElchiCard(padding = PaddingValues(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Box(Modifier.size(64.dp).clip(CircleShape).background(c.soft), contentAlignment = Alignment.Center) {
                val initials = ProfileRules.initials(name)
                if (initials != null) Text(initials, style = Elchi.type.title.copy(fontSize = 22.sp), color = c.softText)
                else ElchiIconView(ElchiIcon.USER, c.softText, size = 28.dp)
            }
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(name?.takeIf { it.isNotBlank() } ?: displayPhone(phone), style = Elchi.type.section.copy(fontSize = 18.sp, fontWeight = FontWeight.SemiBold), color = c.text)
                if (!name.isNullOrBlank()) Text(displayPhone(phone), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = c.muted)
                val ok = c.tone(Tone.OK)
                Text(badge, Modifier.padding(top = 4.dp).clip(CircleShape).background(ok.bg).padding(horizontal = 10.dp, vertical = 4.dp), style = Elchi.type.badge, color = ok.fg)
            }
        }
    }
}

// -- client-profile -----------------------------------------------------------------------------------------------

/** Where the profile's quick actions go. */
data class ProfileNav(
    val onBonus: () -> Unit,
    val onNotifications: () -> Unit,
    val onThreads: () -> Unit,
    val onSafety: () -> Unit,
    val onHelp: () -> Unit,
    val onSignOut: () -> Unit,
)

/**
 * `client-profile` "Profil": who I am, my numbers (v2 only; "—" when they could not be read), my name, and the
 * quick actions in the design's order. No dispute row (Q141: there are no dispute screens).
 */
@Composable
fun ProfileScreen(vm: ProfileViewModel, session: Session, onBack: () -> Unit, nav: ProfileNav, notificationsDot: Boolean = false) {
    val s by vm.state.collectAsStateWithLifecycle()
    var confirmLogout by remember { mutableStateOf(false) }
    val dash = "—"
    StepScaffold(title = t(R.string.clientProfile_title), onBack = onBack, onRefresh = vm::load, refreshing = false) {
        AvatarCard(session.user.fullName, session.user.phone, t(R.string.clientProfile_accountBadge))
        val stats = (s.stats as? Load.Ready)?.value
        if (s.stats is Load.Loading) {
            SkeletonCard(t(R.string.common_loading), lines = 2)
        } else {
            StatTiles(
                listOf(
                    Triple(0, t(R.string.client_profile_statTotal), stats?.total?.toString() ?: dash),
                    Triple(1, t(R.string.clientProfile_statActive), stats?.active?.toString() ?: dash),
                    Triple(2, t(R.string.clientProfile_statBids), stats?.offers?.toString() ?: dash),
                ),
            )
            ElchiCard {
                Text(t(R.string.clientProfile_ordersTitle), Modifier.padding(top = 12.dp), style = Elchi.type.bodyStrong, color = Elchi.colors.text)
                CardRow(t(R.string.client_profile_statCompleted), stats?.completed?.toString() ?: dash)
                CardRow(
                    t(R.string.clientProfile_latestOrder), stats?.latestKey?.let { tOrNull(it) } ?: dash,
                    valueColor = stats?.latestTone?.let { Elchi.colors.tone(it).fg },
                )
            }
        }

        SectionTitle(t(R.string.clientProfile_personalTitle))
        ElchiField(
            value = s.name,
            onValueChange = vm::setName,
            label = t(R.string.clientProfile_fullName),
            placeholder = t(R.string.clientProfile_fullNamePlaceholder),
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words),
            error = if (s.nameTooShort) t(R.string.clientProfile_nameMinChars) else null,
        )
        s.saveError?.let { Note(t(R.string.client_profile_nameSaveFailed, "error" to errorText(it)), tone = Tone.ERR) }
        if (s.saved != null) Note(t(R.string.clientProfile_updated), tone = Tone.OK)
        ElchiButton(
            t(R.string.common_save), vm::saveName, Modifier.fillMaxWidth(), ButtonVariant.PRIMARY, ButtonSize.MEDIUM,
            enabled = ProfileRules.nameToSave(s.name, session.user.fullName) != null, loading = s.saving,
        )

        SectionTitle(t(R.string.clientProfile_quickActions))
        // Profil v3 4.1/4.2: six rows, no hints. Orders, proposals, settings and home stay in the drawer.
        ListCard {
            ListRow(t(R.string.clientProfile_bonus), icon = ElchiIcon.GIFT, first = true, onClick = nav.onBonus)
            ListRow(t(R.string.notifications_title), icon = ElchiIcon.BELL, iconDot = notificationsDot, onClick = nav.onNotifications)
            ListRow(t(R.string.support_myThreads), icon = ElchiIcon.FILE, onClick = nav.onThreads)
            ListRow(t(R.string.safety_centerTitle), icon = ElchiIcon.BLOCK, onClick = nav.onSafety)
            ListRow(t(R.string.clientProfile_help), icon = ElchiIcon.HEAD, onClick = nav.onHelp)
            ListRow(t(R.string.clientProfile_logout), icon = ElchiIcon.LOGOUT, style = ListRowStyle.DANGER, onClick = { confirmLogout = true })
        }
    }
    if (confirmLogout) LogoutConfirm(onConfirm = { confirmLogout = false; nav.onSignOut() }, onDismiss = { confirmLogout = false })
}

// -- client-bonus -------------------------------------------------------------------------------------------------

/**
 * `client-bonus` "Bonuslar va taklif kodi". A bonus is a discount right on a later service, never money (Q16/Q103):
 * no rates, no formulas, nothing to withdraw. With the programme switched off only the balance stays.
 */
@Composable
fun BonusScreen(vm: BonusViewModel, onBack: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    // Stage 09: the driver's "Kredit va taklif kodi" is the same screen with the driver's words and credit.
    val driver = vm.audience == BonusViewModel.DRIVER_AUDIENCE
    StepScaffold(title = t(if (driver) R.string.promoScreen_titleDriver else R.string.promoScreen_titleClient), onBack = onBack, onRefresh = vm::refresh, refreshing = false) {
        val buckets = (s.balance as? Load.Ready)?.value?.let { if (driver) PromoRules.driverBuckets(it.buckets) else PromoRules.clientBuckets(it.buckets) }
        // Design 05: the programme off and nothing to show = only the centred "not running yet" state.
        if (!driver && s.programOff && s.balance is Load.Ready && buckets.isNullOrEmpty()) {
            EmptyState(ElchiIcon.GIFT, t(R.string.promoScreen_programOff), Modifier.padding(top = 24.dp), description = t(R.string.client_bonus_programOffHint))
            return@StepScaffold
        }
        // Profil v3 5.2: the client's short line; the driver keeps the longer credit text (DESIGN09 3.1).
        Note(t(if (driver) R.string.promoScreen_creditNotMoney else R.string.client_v3_bonusNotMoney), tone = Tone.WARN)

        SectionTitle(t(if (driver) R.string.promoScreen_myCredit else R.string.promoScreen_myBonuses))
        when (val balance = s.balance) {
            Load.Loading -> SkeletonCard(t(R.string.common_loading))
            is Load.Failed -> LoadFailed(t(R.string.promoScreen_myBonuses), balance.error, vm::refresh)
            is Load.Ready -> if (buckets.isNullOrEmpty()) {
                if (driver) EmptyState(ElchiIcon.GIFT, t(R.string.driver_bonus_noCreditTitle), description = t(R.string.driver_bonus_noCreditSubtitle))
                else EmptyState(ElchiIcon.GIFT, t(R.string.promoScreen_noBonusTitle), description = t(R.string.promoScreen_noBonusSubtitle))
            } else {
                buckets.forEach { BucketCard(it) }
            }
        }

        if (s.programOff) {
            Note(tOrNull(PromoRules.programOffKey(!buckets.isNullOrEmpty())) ?: t(R.string.promoScreen_programOff), tone = Tone.GRAY)
            return@StepScaffold
        }

        SectionTitle(t(R.string.promoScreen_myCode))
        val code = s.code
        when {
            code != null -> if (driver) DriverCodeCard(code, onCopied = { link -> if (link) vm.markLinkCopied() else vm.markCopied(code.code) }) else CodeCard(code, vm::markCopied)
            s.codeLoading -> SkeletonCard(t(R.string.common_loading), lines = 2)
            else -> s.codeError?.let { LoadFailed(t(R.string.promoScreen_myCode), it, vm::loadCode) }
        }
        // Profil v3 5.3: no reward caption under the code card.

        // Never an amount or a parcel reward here (Q131/Q147, Q103): the accepted code and "it is not replaced".
        if (s.accepted) Note(t(R.string.promoScreen_codeOnce), tone = Tone.OK, title = t(R.string.client_bonus_codeAcceptedValue, "code" to s.acceptedCode.orEmpty()))
        if (!s.hasAttribution && !s.accepted) {
            SectionTitle(t(R.string.promoScreen_enterCode))
            ElchiField(
                value = s.entered,
                onValueChange = vm::setEntered,
                label = t(R.string.promoScreen_friendCode),
                placeholder = t(R.string.promoScreen_codeExample),
                // Profil v3 5.5: no hint, only the error (the "once only" line shows on the accepted card).
                error = when {
                    s.entryErrorKey != null -> tOrNull(s.entryErrorKey!!) ?: t(R.string.promoScreen_codeFormat)
                    s.enterError != null -> errorText(s.enterError!!)
                    else -> null
                },
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters, autoCorrectEnabled = false),
                monospace = true,
            )
            ElchiButton(t(R.string.promoScreen_confirmCode), vm::submitCode, Modifier.fillMaxWidth(), ButtonVariant.SOFT, ButtonSize.MEDIUM, enabled = s.normalized != null, loading = s.entering)
        }

        SectionTitle(t(R.string.promoScreen_myCampaigns))
        when (val referrals = s.referrals) {
            Load.Loading -> SkeletonCard(t(R.string.common_loading), lines = 2)
            is Load.Failed -> LoadFailed(t(R.string.promoScreen_myCampaigns), referrals.error, vm::refresh)
            is Load.Ready -> {
                val invited = referrals.value.invited.let { listOfNotNull(it.attributed, it.qualifying, it.qualified, it.expired, it.rejected).sum() }
                if (referrals.value.enrollments.isEmpty()) Note(t(R.string.promoScreen_noCampaigns), tone = Tone.GRAY)
                referrals.value.enrollments.forEach { item ->
                    val role = t(if (item.side == "referee") R.string.promoScreen_youAreInvited else R.string.promoScreen_youInvited)
                    val status = PromoRules.enrollmentStatusKey(item.qualificationStatus, item.status)?.let { tOrNull(it) } ?: item.status
                    // Design 05: status as a badge, the role line, then one "count · deadline" line (count: inviter only).
                    val meta = listOfNotNull(
                        t(R.string.promoScreen_invitedCount, "count" to invited).takeIf { item.side != "referee" },
                        PromoRules.date(item.qualificationDeadline)?.let { t(R.string.promoScreen_deadline, "date" to it) },
                    ).joinToString(" · ").takeIf { it.isNotEmpty() }
                    // DESIGN09 3.9: the referee's own progress (never the referrer's view of someone else, 3.8).
                    val progress = PromoRules.progressLine(item.side, item.progress)
                    ItemCard(
                        title = item.campaignName,
                        badge = status to PromoRules.enrollmentTone(item.qualificationStatus, item.status),
                        sub = role,
                        lines = listOfNotNull(meta?.let { ItemLine(it) }),
                        footer = if (progress != null) ({ ProgressFooter(progress) }) else null,
                    )
                }
                if (referrals.value.enrollments.isEmpty() && invited > 0) Text(t(R.string.promoScreen_invitedCount, "count" to invited), style = Elchi.type.caption, color = Elchi.colors.muted)
            }
        }
    }
}

/** "2 / 10 safar" and a bar; the grey in-review line when something waits (never counted as done). */
@Composable
private fun ProgressFooter(line: PromoRules.ProgressLine) {
    val c = Elchi.colors
    Text(tOrNull(line.key, "done" to line.done, "required" to line.required) ?: "${line.done} / ${line.required}", style = Elchi.type.label, color = c.text)
    Box(Modifier.fillMaxWidth().height(6.dp).clip(CircleShape).background(c.field)) {
        Box(Modifier.fillMaxWidth(line.fraction).height(6.dp).clip(CircleShape).background(c.brand))
    }
    if (line.inReview) Text(t(R.string.promo_progress_inReviewHint), style = Elchi.type.caption, color = c.muted)
}

@Composable
private fun BucketCard(bucket: PromoBucketDTO) {
    val c = Elchi.colors
    ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 4.dp)) {
        val title = listOfNotNull(tOrNull(PromoRules.instrumentKey(bucket.instrument)), tOrNull(PromoRules.serviceKey(bucket.serviceType))).joinToString(" · ")
        Text(title, Modifier.padding(top = 12.dp, bottom = 2.dp), style = Elchi.type.bodyStrong, color = c.text)
        PromoRules.bucketRows(bucket).forEachIndexed { i, row ->
            val hint = row.hintKey?.takeIf { row.minor > 0 }?.let { tOrNull(it) }
            CardRow(
                tOrNull(row.labelKey) ?: row.labelKey, soum(row.minor), first = i == 0, detail = hint,
                strong = row.usable, valueColor = if (row.usable) c.tone(Tone.OK).fg else null,
            )
        }
        // Design 05: the nearest expiry is the card's sixth row, like iOS.
        PromoRules.date(bucket.nextExpiryAt)?.let { date ->
            CardRow(t(R.string.client_bonus_nextExpiryLabel), date)
        }
    }
}

/**
 * Design 05's navy code card: "Kod", the code in big mono, the link only when a host is configured (else the "not
 * ready" line), "Kodni nusxalash" (the code only) and "Havolani ulashish" (the link, or the code without one).
 */
@Composable
private fun CodeCard(code: ReferralCodeDTO, onCopied: (String) -> Unit) {
    val context = LocalContext.current
    val activity = LocalActivity.current
    val shareTitle = t(R.string.client_share_send)
    val url = PromoRules.shareUrl(code)
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(Elchi.colors.navy).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(t(R.string.client_bonus_codeLabel), style = Elchi.type.caption, color = Color(0xFF9FB6D6))
        Text(
            code.code,
            style = Elchi.type.title.copy(fontFamily = FontFamily.Monospace, fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 4.sp),
            color = Color.White,
        )
        if (url != null) Text(url, style = Elchi.type.label.copy(fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Normal), color = Color(0xFFC9D6E8))
        else Text(t(R.string.promoScreen_linkNotReady), style = Elchi.type.caption, color = Color(0xFFC9D6E8))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ElchiButton(
                t(R.string.client_bonus_copyCode),
                {
                    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("ELCHI", code.code))
                    onCopied(code.code)
                },
                Modifier.weight(1f).height(44.dp), ButtonVariant.PRIMARY, ButtonSize.MEDIUM, horizontalPadding = 10.dp, maxLines = 2,
            )
            ElchiButton(
                if (url != null) t(R.string.client_bonus_shareLink) else shareTitle,
                {
                    val chooser = Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, PromoRules.shareText(code)), shareTitle)
                    activity?.startActivity(chooser) ?: context.startActivity(chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                },
                Modifier.weight(1f).height(44.dp), ButtonVariant.NAVY_LIGHT, ButtonSize.MEDIUM, horizontalPadding = 10.dp, maxLines = 2,
            )
        }
    }
}

/**
 * DESIGN09 3.4: the driver's white card (iOS's `driverCodeCard`): the code centred in big mono, the link in a grey
 * box with "Nusxa olish" (the link when there is one, else the code), then a full-width "Ulashish". No QR on Android:
 * the project has no QR encoder and this stage adds no dependency (reported deviation). [onCopied] gets true when the
 * link was copied.
 */
@Composable
private fun DriverCodeCard(code: ReferralCodeDTO, onCopied: (Boolean) -> Unit) {
    val context = LocalContext.current
    val activity = LocalActivity.current
    val c = Elchi.colors
    val shareTitle = t(R.string.client_share_send)
    val url = PromoRules.shareUrl(code)
    var copied by remember(code.code) { mutableStateOf(false) }
    ElchiCard(padding = PaddingValues(16.dp)) {
        Column(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(
                code.code,
                style = Elchi.type.title.copy(fontFamily = FontFamily.Monospace, fontSize = 26.sp, lineHeight = 32.sp, fontWeight = FontWeight.Bold, letterSpacing = 4.sp),
                color = c.text,
                textAlign = TextAlign.Center,
            )
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(c.field).padding(start = 12.dp, end = 6.dp, top = 6.dp, bottom = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    url ?: t(R.string.promoScreen_linkNotReady),
                    Modifier.weight(1f),
                    style = if (url != null) Elchi.type.label.copy(fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Normal) else Elchi.type.caption,
                    color = if (url != null) c.accentText else c.muted,
                )
                ElchiButton(
                    t(if (copied) R.string.promoScreen_copied else R.string.promoScreen_copy),
                    {
                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        clipboard.setPrimaryClip(ClipData.newPlainText("ELCHI", PromoRules.shareText(code)))
                        copied = true
                        onCopied(url != null)
                    },
                    Modifier.height(40.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM, horizontalPadding = 12.dp, icon = if (copied) ElchiIcon.CHECK else ElchiIcon.COPY,
                )
            }
            ElchiButton(
                shareTitle,
                {
                    val chooser = Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, PromoRules.shareText(code)), shareTitle)
                    activity?.startActivity(chooser) ?: context.startActivity(chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                },
                Modifier.fillMaxWidth(), ButtonVariant.PRIMARY, ButtonSize.MEDIUM, icon = ElchiIcon.SHARE,
            )
        }
    }
}

// -- settings -----------------------------------------------------------------------------------------------------

private const val PRIVACY_URL = "https://www.elchigo.uz/privacy"

/**
 * `settings` "Sozlamalar": appearance (light / dark / follow the phone, live), language (live), account (help,
 * privacy policy in the browser, delete), sign-out, version. No notification toggles: there is no push (Q82).
 */
@Composable
fun SettingsScreen(
    themeMode: ThemeMode,
    onTheme: (ThemeMode) -> Unit,
    locale: AppLocale,
    onLocale: (AppLocale) -> Unit,
    onBack: () -> Unit,
    onHelp: () -> Unit,
    onDeleteAccount: () -> Unit,
    onSignOut: () -> Unit,
    /** Where "Mavzu: Qorong'i" / "Til: Русский" show after a change (design 05 toasts); null = nowhere. */
    banners: BannerCenter? = null,
) {
    val context = LocalContext.current
    val activity = LocalActivity.current
    var confirmLogout by remember { mutableStateOf(false) }
    StepScaffold(title = t(R.string.settingsScreen_title), onBack = onBack) {
        SectionTitle(t(R.string.settingsScreen_appearance))
        ThemeTiles(themeMode) { mode ->
            if (mode != themeMode) {
                onTheme(mode)
                val nameKey = when (mode) {
                    ThemeMode.LIGHT -> "client.settings.themeLight"
                    ThemeMode.DARK -> "client.settings.themeDark"
                    ThemeMode.SYSTEM -> "client.settings.themeSystem"
                }
                banners?.show(BannerTone.OK, BannerText.Key("client.settings.themeChanged", keyParams = mapOf("name" to nameKey)))
            }
        }
        SectionTitle(t(R.string.settings_language), description = t(R.string.settings_languageHint))
        Segmented(AppLocale.entries.map { it to it.label }, locale, onSelect = { next: AppLocale ->
            if (next != locale) {
                onLocale(next)
                banners?.show(BannerTone.OK, BannerText.Key("client.settings.languageChanged", params = mapOf("name" to next.label)))
            }
        })
        Text(t(R.string.client_settings_mapLanguageNote), style = Elchi.type.caption, color = Elchi.colors.muted)

        SectionTitle(t(R.string.settingsScreen_account))
        ListCard {
            ListRow(t(R.string.support_title), icon = ElchiIcon.HEAD, first = true, onClick = onHelp)
            ListRow(t(R.string.settingsScreen_privacy), icon = ElchiIcon.SHIELD, onClick = {
                val open = Intent(Intent.ACTION_VIEW, PRIVACY_URL.toUri())
                runCatching { activity?.startActivity(open) ?: context.startActivity(open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            })
            ListRow(t(R.string.client_settings_deleteAccount), icon = ElchiIcon.TRASH, style = ListRowStyle.DANGER, dangerChevron = true, onClick = onDeleteAccount)
        }
        ListCard {
            ListRow(t(R.string.settingsScreen_logout), icon = ElchiIcon.LOGOUT, first = true, style = ListRowStyle.DANGER, onClick = { confirmLogout = true })
        }
        Text(
            t(R.string.client_settings_version, "version" to BuildConfig.VERSION_NAME),
            Modifier.fillMaxWidth().padding(top = 4.dp),
            style = Elchi.type.caption.copy(fontSize = 11.sp),
            color = Elchi.colors.muted,
            textAlign = TextAlign.Center,
        )
    }
    if (confirmLogout) LogoutConfirm(onConfirm = { confirmLogout = false; onSignOut() }, onDismiss = { confirmLogout = false })
}

/**
 * Design 05's appearance tiles: an icon (sun / moon / monitor), the name, then the hint under it; the chosen tile
 * outlined 2dp in brand (a radio for TalkBack).
 */
@Composable
private fun ThemeTiles(selected: ThemeMode, onSelect: (ThemeMode) -> Unit) {
    val c = Elchi.colors
    val items = listOf(
        Triple(ThemeMode.LIGHT, ElchiIcon.SUN, t(R.string.client_settings_themeLight) to t(R.string.client_settings_themeLightHint)),
        Triple(ThemeMode.DARK, ElchiIcon.MOON, t(R.string.client_settings_themeDark) to t(R.string.client_settings_themeDarkHint)),
        Triple(ThemeMode.SYSTEM, ElchiIcon.MONITOR, t(R.string.client_settings_themeSystem) to t(R.string.client_settings_themeSystemHint)),
    )
    Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items.forEach { (mode, icon, words) ->
            val active = mode == selected
            val shape = RoundedCornerShape(18.dp)
            Column(
                Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .shadow(8.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
                    .clip(shape)
                    .background(c.card)
                    .border(if (active) 2.dp else 1.dp, if (active) c.brand else c.line, shape)
                    .selectable(active, role = Role.RadioButton) { onSelect(mode) }
                    .padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                ElchiIconView(icon, if (active) c.accentText else c.text, size = 22.dp)
                Text(words.first, style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = c.text, maxLines = 1)
                Text(words.second, style = Elchi.type.caption.copy(fontSize = 11.5.sp, lineHeight = 15.sp), color = c.muted)
            }
        }
    }
}

// -- account-delete -----------------------------------------------------------------------------------------------

/**
 * `account-delete` "Akkauntni o'chirish": what goes, what stays (anonymised records), when (at once - the server
 * anonymises immediately), a confirmation tick, then `DELETE /me`. A refusal lists what is still open.
 */
@Composable
fun AccountDeleteScreen(vm: AccountDeleteViewModel, onBack: () -> Unit, onDeleted: () -> Unit, onOrders: (() -> Unit)? = null) {
    val s by vm.state.collectAsStateWithLifecycle()
    var confirm by rememberSaveable { mutableStateOf(false) }
    StepScaffold(
        title = t(R.string.client_accountDelete_title),
        onBack = onBack,
        footer = {
            ElchiButton(
                t(R.string.client_accountDelete_submit), { confirm = true }, Modifier.fillMaxWidth(), ButtonVariant.DANGER,
                enabled = s.confirmed, loading = s.submitting,
            )
            ElchiButton(t(R.string.confirmDialog_back), onBack, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, enabled = !s.submitting)
        },
    ) {
        Note(t(R.string.client_accountDelete_warn), tone = Tone.WARN)
        ElchiCard {
            CardRow(t(R.string.client_accountDelete_deletedLabel), t(R.string.client_accountDelete_deletedValue), first = true)
            CardRow(t(R.string.client_accountDelete_keptLabel), t(R.string.client_accountDelete_keptValue))
            CardRow(t(R.string.client_accountDelete_whenLabel), t(R.string.client_accountDelete_whenValue))
        }
        s.blockers?.let { lines ->
            val err = Elchi.colors.tone(Tone.ERR)
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(err.bg).padding(horizontal = 14.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                    ElchiIconView(ElchiIcon.ALERT, err.fg, size = 18.dp)
                    Text(t(R.string.client_accountDelete_blockedTitle), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = err.noteText)
                }
                lines.forEach { line ->
                    val text = if (line.count != null) tOrNull(line.key, "count" to line.count) else tOrNull(line.key)
                    Text("• ${text ?: line.key}", Modifier.padding(start = 28.dp), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = err.noteText)
                }
                if (onOrders != null && DeletionRules.leadsToOrders(lines)) {
                    Text(
                        t(R.string.client_settings_goToOrders),
                        Modifier.padding(start = 28.dp).heightIn(min = 36.dp).clip(RoundedCornerShape(8.dp)).clickable(role = Role.Button, onClick = onOrders).padding(vertical = 8.dp),
                        style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold, textDecoration = TextDecoration.Underline),
                        color = err.noteText,
                    )
                }
            }
        }
        s.error?.let { Note(errorText(it), tone = Tone.ERR) }
        val border = Elchi.colors.line
        Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).border(1.dp, border, RoundedCornerShape(14.dp)).padding(horizontal = 12.dp, vertical = 4.dp)) {
            CheckRow(t(R.string.client_v3_deleteCheck), s.confirmed, vm::setConfirmed)
        }
    }
    // Design 05's last question before `DELETE /me`; the text is the app's (deletion is immediate, no 30 days).
    if (confirm) {
        ElchiDialog(
            title = t(R.string.client_settings_deleteConfirmTitle),
            text = t(R.string.client_accountDelete_whenValue),
            confirm = t(R.string.client_settings_deleteConfirmYes),
            onConfirm = {
                confirm = false
                vm.submit(onDeleted)
            },
            onDismiss = { confirm = false },
            confirmVariant = ButtonVariant.DANGER,
            dismiss = t(R.string.confirmDialog_back),
        )
    }
}
