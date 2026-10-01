package uz.elchi.app.feature.entry

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.autofill.ContentType
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.contentType
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.input.TransformedText
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.BuildConfig
import uz.elchi.app.R
import uz.elchi.app.i18n.AppLocale
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.session.MobileRole
import uz.elchi.app.ui.components.Banner
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.Chip
import uz.elchi.app.ui.components.ChoiceCard
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.ElchiLogo
import uz.elchi.app.ui.components.Heading
import uz.elchi.app.ui.components.OtpCells
import uz.elchi.app.ui.components.PageDots
import uz.elchi.app.ui.components.Segmented
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.components.TopBar
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

/** Screen skeleton shared by the entry flow: top bar, scrolling body, footer pinned above the keyboard. */
@Composable
private fun EntryScaffold(
    top: @Composable () -> Unit,
    footer: @Composable ColumnScope.() -> Unit,
    body: @Composable ColumnScope.() -> Unit,
) {
    SystemBarIcons(dark = !Elchi.colors.isDark)
    Column(Modifier.fillMaxSize().background(Elchi.colors.page).systemBarsPadding().imePadding()) {
        top()
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            content = body,
        )
        Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp), content = footer)
    }
}

// -- 01 Splash --------------------------------------------------------------------------------------------------

/**
 * Always navy, whatever the theme (the prototype's splash). Says only what is true today: parcels between cities
 * (passenger service is off, K7/Q5) - no counts, no promises.
 */
@Composable
fun SplashScreen(onStart: () -> Unit) {
    val c = Elchi.colors
    SystemBarIcons(dark = false)
    Column(
        Modifier.fillMaxSize().background(c.navy).systemBarsPadding().padding(horizontal = 28.dp).padding(top = 100.dp, bottom = 20.dp),
    ) {
        ElchiLogo(height = 47.dp)
        Text(t(R.string.entry_tagline), Modifier.padding(top = 18.dp), style = Elchi.type.body.copy(fontSize = 17.sp, lineHeight = 26.sp), color = Color(0xFFB8C6DE))
        // Route motif: origin ring - dashed road - destination pin (decorative).
        Row(Modifier.padding(top = 44.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(16.dp).border(3.dp, c.brand, CircleShape))
            Box(Modifier.weight(1f).padding(horizontal = 10.dp).height(2.dp).background(Color(0xFF3C5A8C)))
            ElchiIconView(ElchiIcon.PIN, c.brand, size = 20.dp)
        }
        Spacer(Modifier.weight(1f))
        ElchiButton(t(R.string.onboarding_start), onStart, Modifier.fillMaxWidth())
        Text(t(R.string.entry_footer), Modifier.fillMaxWidth().padding(top = 20.dp), style = Elchi.type.caption, color = Color(0xFF8FA2C4), textAlign = TextAlign.Center)
    }
}

// -- 02 Onboarding ----------------------------------------------------------------------------------------------

private data class OnboardingStep(val icon: ElchiIcon, val tone: Tone, val title: Int, val text: Int)

private val STEPS = listOf(
    OnboardingStep(ElchiIcon.PIN, Tone.BLUE, R.string.onboarding_step1Title, R.string.onboarding_step1Text),
    OnboardingStep(ElchiIcon.TAG, Tone.OK, R.string.onboarding_step2Title, R.string.onboarding_step2Text),
    // Q139/Q144: the old "confirm and rate" step is gone - an operator records delivery.
    OnboardingStep(ElchiIcon.CHECK_C, Tone.WARN, R.string.onboarding_step3OperatorTitle, R.string.onboarding_step3OperatorText),
)

@Composable
fun OnboardingScreen(onDone: () -> Unit) {
    var step by rememberSaveable { mutableIntStateOf(0) }
    val current = STEPS[step]
    val colors = Elchi.colors.tone(current.tone)
    EntryScaffold(
        top = { Box(Modifier.padding(start = 20.dp, top = 14.dp)) { ElchiLogo(height = 30.dp) } },
        footer = {
            val last = step == STEPS.lastIndex
            ElchiButton(t(if (last) R.string.onboarding_start else R.string.onboarding_next), { if (last) onDone() else step++ }, Modifier.fillMaxWidth())
            if (!last) ElchiButton(t(R.string.onboarding_skip), onDone, Modifier.fillMaxWidth(), ButtonVariant.GHOST, ButtonSize.MEDIUM)
        },
    ) {
        Column(Modifier.fillMaxWidth().padding(top = 20.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(20.dp)) {
            Box(Modifier.size(128.dp).clip(RoundedCornerShape(36.dp)).background(colors.bg), contentAlignment = Alignment.Center) {
                ElchiIconView(current.icon, colors.fg, size = 60.dp)
            }
            PageDots(STEPS.size, step)
            Text(t(current.title), style = Elchi.type.title.copy(fontSize = 26.sp, lineHeight = 31.sp), color = Elchi.colors.text, textAlign = TextAlign.Center)
            Text(t(current.text), Modifier.widthIn(max = 300.dp), style = Elchi.type.body.copy(lineHeight = 23.sp), color = Elchi.colors.muted, textAlign = TextAlign.Center)
        }
    }
}

// -- 03 Role ----------------------------------------------------------------------------------------------------

/**
 * The role is permanent for a phone number (the server refuses the other role: ROLE_MISMATCH), so the subtitle
 * says so instead of the old "you can change it later". The language choice lives here (design note).
 */
@Composable
fun RoleScreen(locale: AppLocale, onLocale: (AppLocale) -> Unit, onBack: (() -> Unit)?, onRole: (MobileRole) -> Unit) {
    EntryScaffold(
        top = { TopBar(onBack, t(R.string.common_back), logo = true) },
        footer = { Text(t(R.string.entry_footer), Modifier.fillMaxWidth(), style = Elchi.type.caption, color = Elchi.colors.muted, textAlign = TextAlign.Center) },
    ) {
        Heading(t(R.string.onboarding_roleTitle), subtitle = t(R.string.onboarding_roleSubtitlePermanent))
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            ChoiceCard(ElchiIcon.PKG, t(R.string.onboarding_roleClient), t(R.string.onboarding_roleClientHint), { onRole(MobileRole.CLIENT) })
            ChoiceCard(ElchiIcon.TRUCK, t(R.string.onboarding_roleDriver), t(R.string.onboarding_roleDriverHint), { onRole(MobileRole.DRIVER) })
        }
        Segmented(AppLocale.entries.map { it to it.label }, locale, onLocale)
    }
}

// -- 04 Phone ---------------------------------------------------------------------------------------------------

/** `901234567` shown as `90 123 45 67`; the cursor maps back onto the raw digits. */
internal object UzPhoneTransformation : VisualTransformation {
    private val breaks = setOf(2, 5, 7)

    override fun filter(text: androidx.compose.ui.text.AnnotatedString): TransformedText {
        val raw = text.text
        val out = buildString { raw.forEachIndexed { i, ch -> if (i in breaks) append(' '); append(ch) } }
        val mapping = object : OffsetMapping {
            override fun originalToTransformed(offset: Int) = offset + breaks.count { it < offset }
            override fun transformedToOriginal(offset: Int): Int {
                var original = 0
                var transformed = 0
                while (original < raw.length && transformed < offset) {
                    if (original in breaks) transformed++
                    if (transformed >= offset) break
                    original++
                    transformed++
                }
                return original.coerceAtMost(raw.length)
            }
        }
        return TransformedText(androidx.compose.ui.text.AnnotatedString(out), mapping)
    }
}

@Composable
fun PhoneScreen(vm: SignInViewModel, onBack: () -> Unit, onSent: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { focus.requestFocus() }
    EntryScaffold(
        top = { TopBar(onBack, t(R.string.common_back)) },
        footer = {
            ElchiButton(t(R.string.auth_getCode), { vm.requestCode(onSent) }, Modifier.fillMaxWidth(), icon = ElchiIcon.SEND, enabled = s.phoneValid, loading = s.sending)
        },
    ) {
        Row {
            Chip(
                t(if (s.role == MobileRole.CLIENT) R.string.auth_asClient else R.string.auth_asDriver),
                selected = true,
                onClick = onBack,
                icon = if (s.role == MobileRole.CLIENT) ElchiIcon.PKG else ElchiIcon.TRUCK,
            )
        }
        Heading(t(R.string.auth_phoneTitle), subtitle = t(R.string.auth_phoneSubtitle))
        // One field with a fixed prefix; the digits are formatted as they are typed (design note).
        Row(
            Modifier.fillMaxWidth().height(56.dp).clip(RoundedCornerShape(16.dp)).background(c.field)
                .then(if (s.error != null) Modifier.border(1.5.dp, c.tone(Tone.ERR).fg, RoundedCornerShape(16.dp)) else Modifier)
                .padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("+998", style = Elchi.type.bodyStrong.copy(fontSize = 17.sp), color = c.text)
            Box(Modifier.size(width = 1.dp, height = 22.dp).background(c.outline))
            BasicTextField(
                value = s.digits,
                onValueChange = vm::onDigits,
                singleLine = true,
                textStyle = Elchi.type.body.copy(fontSize = 17.sp, color = c.text, fontFamily = FontFamily.Monospace),
                cursorBrush = androidx.compose.ui.graphics.SolidColor(c.brand),
                visualTransformation = UzPhoneTransformation,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { vm.requestCode(onSent) }),
                modifier = Modifier.weight(1f).focusRequester(focus).semantics { contentType = ContentType.PhoneNumber },
                decorationBox = { inner ->
                    Box(contentAlignment = Alignment.CenterStart) {
                        if (s.digits.isEmpty()) Text("90 123 45 67", style = Elchi.type.body.copy(fontSize = 17.sp, fontFamily = FontFamily.Monospace), color = c.placeholder)
                        inner()
                    }
                },
            )
        }
        s.error?.let { Text(errorText(it), style = Elchi.type.caption, color = c.tone(Tone.ERR).fg) }
    }
}

// -- 05 OTP -----------------------------------------------------------------------------------------------------

@Composable
fun OtpScreen(vm: SignInViewModel, onBack: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { focus.requestFocus() }
    EntryScaffold(
        top = {
            Column {
                TopBar(onBack, t(R.string.common_back))
                when {
                    s.error != null -> Banner(errorText(s.error!!), Tone.ERR)
                    s.codeSent -> Banner(t(R.string.auth_codeSent), Tone.OK)
                }
            }
        },
        footer = {
            ElchiButton(t(R.string.common_confirm), vm::verify, Modifier.fillMaxWidth(), icon = ElchiIcon.CHEV_R, enabled = s.code.length == vm.otpLength, loading = s.verifying)
        },
    ) {
        Heading(t(R.string.auth_otpTitle), subtitle = "${t(R.string.auth_otpSentTo)}: ${formatPhone(s.phone)}", centered = true)
        Text(t(R.string.auth_otpLabel, "length" to vm.otpLength), Modifier.fillMaxWidth(), style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.Medium), color = c.text, textAlign = TextAlign.Center)
        // The digits go into one hidden field (SMS autofill, paste, the number pad); the circles only draw it.
        val otpLabel = t(R.string.auth_otpLabel, "length" to vm.otpLength)
        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            BasicTextField(
                value = TextFieldValue(s.code, TextRange(s.code.length)),
                onValueChange = { vm.onCode(it.text) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done),
                modifier = Modifier.size(1.dp).focusRequester(focus).semantics {
                    contentType = ContentType.SmsOtpCode
                    contentDescription = otpLabel
                },
                textStyle = Elchi.type.body.copy(color = Color.Transparent),
                cursorBrush = androidx.compose.ui.graphics.SolidColor(Color.Transparent),
            )
            OtpCells(
                s.code,
                vm.otpLength,
                Modifier.fillMaxWidth().clickable(remember { MutableInteractionSource() }, indication = null) { focus.requestFocus() },
                error = s.codeRejected,
            )
        }
        if (s.resendIn > 0) {
            Text(t(R.string.auth_resendIn, "seconds" to s.resendIn.toString().padStart(2, '0')), Modifier.fillMaxWidth(), style = Elchi.type.secondary.copy(fontFamily = FontFamily.Monospace), color = c.muted, textAlign = TextAlign.Center)
        } else {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                ElchiButton(t(R.string.auth_resendCode), vm::resend, variant = ButtonVariant.GHOST, size = ButtonSize.MEDIUM, icon = ElchiIcon.REFRESH, loading = s.sending)
            }
        }
        if (BuildConfig.DEBUG && s.devOtp != null) {
            Text(t(R.string.auth_devCode, "code" to s.devOtp!!), Modifier.fillMaxWidth(), style = Elchi.type.caption, color = c.muted, textAlign = TextAlign.Center)
        }
    }
}

private fun formatPhone(phone: String): String {
    val d = phone.removePrefix("+998")
    return if (d.length == 9) "+998 ${d.take(2)} ${d.substring(2, 5)} ${d.substring(5, 7)} ${d.substring(7)}" else phone
}
