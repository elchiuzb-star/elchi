package uz.elchi.app.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.ElchiShape
import uz.elchi.app.ui.theme.ThemeMode
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

// -- icons ------------------------------------------------------------------------------------------------------

@Composable
fun ElchiIconView(icon: ElchiIcon, tint: Color, modifier: Modifier = Modifier, size: Dp = 20.dp, contentDescription: String? = null) {
    Icon(painterResource(icon.res), contentDescription, modifier.size(size), tint = tint)
}

// -- buttons ----------------------------------------------------------------------------------------------------

/** The prototype's button variants (`BV` in elchi-mobile.js). */
enum class ButtonVariant { PRIMARY, SOFT, NEUTRAL, DANGER_SOFT, OUTLINE, GHOST, DANGER, NAVY }

enum class ButtonSize(val height: Dp) { LARGE(56.dp), MEDIUM(44.dp) }

private data class ButtonColors(val bg: Color, val fg: Color, val border: Color?)

@Composable
private fun buttonColors(variant: ButtonVariant): ButtonColors {
    val c = Elchi.colors
    return when (variant) {
        ButtonVariant.PRIMARY -> ButtonColors(c.brand, c.onBrand, null)
        ButtonVariant.SOFT -> ButtonColors(c.soft, c.softText, null)
        ButtonVariant.NEUTRAL -> ButtonColors(c.field, c.text, null)
        ButtonVariant.DANGER_SOFT -> c.tone(Tone.ERR).let { ButtonColors(it.bg, it.fg, null) }
        ButtonVariant.OUTLINE -> ButtonColors(Color.Transparent, c.text, c.outline)
        ButtonVariant.GHOST -> ButtonColors(Color.Transparent, c.accentText, null)
        ButtonVariant.DANGER -> ButtonColors(c.danger, Color.White, null)
        ButtonVariant.NAVY -> ButtonColors(if (c.isDark) Color(0xFF1B3563) else c.navy, Color.White, null)
    }
}

/**
 * Pill button. Disabled is the prototype's `x` variant (grey, not faded brand) so it still reads in sunlight;
 * loading keeps the size and shows a spinner instead of the label.
 */
@Composable
fun ElchiButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    variant: ButtonVariant = ButtonVariant.PRIMARY,
    size: ButtonSize = ButtonSize.LARGE,
    icon: ElchiIcon? = null,
    enabled: Boolean = true,
    loading: Boolean = false,
    /** The prototype's paired buttons (`btns`) use 10dp so a longer label ("Boshqa narx (2 marta qoldi)") fits. */
    horizontalPadding: Dp = 18.dp,
    /** 2 lets a paired button's long label wrap ("Muammo haqida xabar berish") instead of being cut. */
    maxLines: Int = 1,
) {
    val c = Elchi.colors
    val colors = if (enabled) buttonColors(variant) else ButtonColors(if (c.isDark) Color(0xFF24272E) else Color(0xFFE4E9EF), if (c.isDark) Color(0xFF6B7482) else Color(0xFF8A96A6), null)
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val shape = CircleShape
    Row(
        modifier
            .height(size.height)
            .clip(shape)
            .background(colors.bg)
            .then(if (colors.border != null) Modifier.border(BorderStroke(1.5.dp, colors.border), shape) else Modifier)
            .clickable(interaction, ripple(color = colors.fg), enabled = enabled && !loading, role = Role.Button, onClick = onClick)
            .alpha(if (pressed) 0.9f else 1f)
            .padding(horizontal = horizontalPadding),
        horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (loading) {
            CircularProgressIndicator(Modifier.size(22.dp), color = colors.fg, strokeWidth = 2.5.dp)
        } else {
            if (icon != null) ElchiIconView(icon, colors.fg, size = 18.dp)
            Text(
                text,
                style = (if (size == ButtonSize.LARGE) Elchi.type.button else Elchi.type.buttonSmall).let { if (maxLines > 1) it.copy(lineHeight = androidx.compose.ui.unit.TextUnit(16f, androidx.compose.ui.unit.TextUnitType.Sp)) else it },
                color = colors.fg,
                maxLines = maxLines,
                overflow = TextOverflow.Ellipsis,
                textAlign = if (maxLines > 1) androidx.compose.ui.text.style.TextAlign.Center else null,
            )
        }
    }
}

/**
 * 44dp round button floating over a map or sheet (profile, back, locate). [dot] is the small red mark on the menu
 * button when something unread waits; the caller puts it into [contentDescription] too. [tint] colours the icon
 * (default: the text colour); [loading] swaps it for a small spinner (the button stays tappable).
 */
@Composable
fun RoundIconButton(icon: ElchiIcon, contentDescription: String, onClick: () -> Unit, modifier: Modifier = Modifier, dot: Boolean = false, tint: Color? = null, loading: Boolean = false) {
    val c = Elchi.colors
    Box(modifier.size(44.dp)) {
        Box(
            Modifier
                .fillMaxSize()
                .shadow(12.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
                .clip(CircleShape)
                .background(c.card)
                .clickable(role = Role.Button, onClick = onClick)
                .semantics { this.contentDescription = contentDescription },
            contentAlignment = Alignment.Center,
        ) {
            if (loading) CircularProgressIndicator(Modifier.size(18.dp), color = c.brand, strokeWidth = 2.dp) else ElchiIconView(icon, tint ?: c.text)
        }
        if (dot) {
            Box(Modifier.align(Alignment.TopEnd).padding(top = 7.dp, end = 7.dp).size(10.dp).clip(CircleShape).background(c.card).padding(1.5.dp).clip(CircleShape).background(c.tone(Tone.ERR).fg))
        }
    }
}

/** Sun / moon pill from the prototype's top bar; a second tap on the active one returns to "follow the phone". */
@Composable
fun ThemeSwitch(mode: ThemeMode, onChange: (ThemeMode) -> Unit, lightLabel: String, darkLabel: String, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    Row(
        modifier
            .shadow(12.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(CircleShape)
            .background(c.card)
            .padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        val lightActive = mode == ThemeMode.LIGHT || (mode == ThemeMode.SYSTEM && !c.isDark)
        listOf(Triple(ElchiIcon.SUN, ThemeMode.LIGHT, lightLabel), Triple(ElchiIcon.MOON, ThemeMode.DARK, darkLabel)).forEach { (icon, target, label) ->
            val active = if (target == ThemeMode.LIGHT) lightActive else !lightActive
            Box(
                Modifier
                    .size(36.dp)
                    .clip(CircleShape)
                    .background(if (active) c.brand else Color.Transparent)
                    .selectable(selected = mode == target, role = Role.RadioButton) { onChange(if (mode == target) ThemeMode.SYSTEM else target) }
                    .semantics { contentDescription = label },
                contentAlignment = Alignment.Center,
            ) { ElchiIconView(icon, if (active) c.onBrand else c.muted, size = 18.dp) }
        }
    }
}

// -- text blocks ------------------------------------------------------------------------------------------------

@Composable
fun Heading(title: String, modifier: Modifier = Modifier, subtitle: String? = null, large: Boolean = false, centered: Boolean = false) {
    val align = if (centered) Alignment.CenterHorizontally else Alignment.Start
    val textAlign = if (centered) androidx.compose.ui.text.style.TextAlign.Center else null
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp), horizontalAlignment = align) {
        Text(title, style = if (large) Elchi.type.display else Elchi.type.title, color = Elchi.colors.text, textAlign = textAlign)
        if (subtitle != null) Text(subtitle, style = Elchi.type.secondary, color = Elchi.colors.muted, textAlign = textAlign)
    }
}

@Composable
fun SectionTitle(title: String, modifier: Modifier = Modifier, description: String? = null, action: String? = null, onAction: (() -> Unit)? = null) {
    Column(modifier.padding(top = 4.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(title, Modifier.weight(1f), style = Elchi.type.section, color = Elchi.colors.text)
            if (action != null) {
                Text(
                    action,
                    Modifier.clickable(enabled = onAction != null, role = Role.Button) { onAction?.invoke() },
                    style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold),
                    color = Elchi.colors.accentText,
                )
            }
        }
        if (description != null) Text(description, style = Elchi.type.caption, color = Elchi.colors.muted)
    }
}

// -- surfaces ---------------------------------------------------------------------------------------------------

/**
 * The prototype's card. [background] replaces the white surface (the blue "total" card, the grey summary card) and
 * drops the shadow with it, as the prototype does; [bordered] adds its hairline border.
 */
@Composable
fun ElchiCard(
    modifier: Modifier = Modifier,
    padding: PaddingValues = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
    onClick: (() -> Unit)? = null,
    background: Color? = null,
    bordered: Boolean = false,
    content: @Composable ColumnScope.() -> Unit,
) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(ElchiShape.card)
    Column(
        modifier
            .fillMaxWidth()
            .then(if (background == null) Modifier.shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow) else Modifier)
            .clip(shape)
            .background(background ?: c.card)
            .then(if (bordered && background == null) Modifier.border(1.dp, c.line, shape) else Modifier)
            .then(if (onClick != null) Modifier.clickable(role = Role.Button, onClick = onClick) else Modifier)
            .padding(padding),
        content = content,
    )
}

/** A card's own title line, with an optional badge on the right (a policy version, a status). */
@Composable
fun CardHeader(title: String, badge: String? = null, badgeTone: Tone = Tone.BLUE) {
    Row(Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(title, Modifier.weight(1f), style = Elchi.type.bodyStrong, color = Elchi.colors.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (badge != null) {
            val colors = Elchi.colors.tone(badgeTone)
            Text(badge, Modifier.clip(CircleShape).background(colors.bg).padding(horizontal = 10.dp, vertical = 4.dp), style = Elchi.type.badge, color = colors.fg, maxLines = 1)
        }
    }
}

/**
 * A key/value row inside an [ElchiCard]; rows after the first draw the hairline above themselves. [strong] is the
 * prototype's semibold value (totals, the route time); [muted] greys a value that is a placeholder ("not set").
 * [onTrailing] makes the trailing pill a button ("O'zgartirish") with a 44dp touch target.
 */
@Composable
fun CardRow(
    key: String,
    value: String,
    first: Boolean = false,
    detail: String? = null,
    trailing: String? = null,
    onTrailing: (() -> Unit)? = null,
    strong: Boolean = false,
    muted: Boolean = false,
) {
    val c = Elchi.colors
    Column {
        if (!first) Spacer(Modifier.fillMaxWidth().height(1.dp).background(c.field))
        Row(Modifier.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(key, style = Elchi.type.caption, color = c.muted)
                Text(
                    value,
                    style = Elchi.type.secondary.copy(fontWeight = if (strong) androidx.compose.ui.text.font.FontWeight.SemiBold else androidx.compose.ui.text.font.FontWeight.Medium),
                    color = if (muted) c.placeholder else c.text,
                )
                if (detail != null) Text(detail, style = Elchi.type.caption, color = c.muted)
            }
            if (trailing != null) {
                Box(
                    Modifier
                        .heightIn(min = 44.dp)
                        .then(if (onTrailing != null) Modifier.clickable(role = Role.Button, onClick = onTrailing) else Modifier),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        trailing,
                        Modifier.clip(CircleShape).background(c.field).padding(horizontal = 12.dp, vertical = 6.dp),
                        style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold),
                        color = c.accentText,
                        maxLines = 1,
                    )
                }
            }
        }
    }
}

/** The rounded-top panel that holds a screen's controls over a map (the prototype's bottom sheet). */
@Composable
fun BottomPanel(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(topStart = ElchiShape.sheet, topEnd = ElchiShape.sheet))
            .background(Elchi.colors.card)
            .padding(start = 16.dp, end = 16.dp, top = 24.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        content = content,
    )
}

@Composable
fun Note(text: String, modifier: Modifier = Modifier, tone: Tone = Tone.BLUE, title: String? = null) {
    val colors = Elchi.colors.tone(tone)
    val icon = when (tone) {
        Tone.WARN, Tone.ERR -> ElchiIcon.ALERT
        Tone.OK -> ElchiIcon.CHECK_C
        else -> ElchiIcon.INFO
    }
    val bg = if (tone == Tone.BLUE && !Elchi.colors.isDark) Color(0xFFEEF6FF) else colors.bg
    Row(
        modifier.fillMaxWidth().clip(RoundedCornerShape(ElchiShape.note)).background(bg).padding(horizontal = 14.dp, vertical = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        ElchiIconView(icon, colors.fg, Modifier.padding(top = 1.dp), size = 18.dp)
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            if (title != null) Text(title, style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold), color = colors.noteText)
            Text(text, style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.Normal, lineHeight = Elchi.type.secondary.lineHeight), color = colors.noteText)
        }
    }
}

/**
 * "Taklif kodi saqlandi: … — tasdiqlash uchun bosing": the referral code kept from a link (web client and driver
 * home). A pale-blue row with the brand outline; [loading] while the tap's request runs.
 */
@Composable
fun PendingReferralRow(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, loading: Boolean = false) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(14.dp)
    Row(
        modifier
            .fillMaxWidth()
            .clip(shape)
            .background(c.highlight)
            .border(1.dp, c.brand.copy(alpha = 0.3f), shape)
            .clickable(enabled = !loading, role = Role.Button, onClick = onClick)
            .heightIn(min = 48.dp)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        ElchiIconView(ElchiIcon.GIFT, c.accentText, size = 18.dp)
        Text(text, Modifier.weight(1f), style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold), color = c.accentText)
        if (loading) CircularProgressIndicator(Modifier.size(16.dp), color = c.brand, strokeWidth = 2.dp)
        else ElchiIconView(ElchiIcon.CHEV_R, c.accentText, size = 16.dp)
    }
}

/** Status pill with a dot: the dot keeps the meaning when colour cannot (greyscale, sunlight). */
@Composable
fun Badge(text: String, tone: Tone, modifier: Modifier = Modifier) {
    val colors = Elchi.colors.tone(tone)
    Row(
        modifier.clip(CircleShape).background(colors.bg).padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        Box(Modifier.size(6.dp).clip(CircleShape).background(colors.fg))
        Text(text, style = Elchi.type.badge, color = colors.fg, maxLines = 1)
    }
}

// -- inputs -----------------------------------------------------------------------------------------------------

/**
 * Text field: label above, optional fixed prefix (`+998`) behind a divider, hint or error below. [error] replaces
 * the hint and adds an error-tone border so the state is not colour-only.
 */
@Composable
fun ElchiField(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    label: String? = null,
    placeholder: String? = null,
    prefix: String? = null,
    icon: ElchiIcon? = null,
    hint: String? = null,
    error: String? = null,
    enabled: Boolean = true,
    keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
    keyboardActions: KeyboardActions = KeyboardActions.Default,
    singleLine: Boolean = true,
    minHeight: Dp = 52.dp,
    visualTransformation: androidx.compose.ui.text.input.VisualTransformation = androidx.compose.ui.text.input.VisualTransformation.None,
    monospace: Boolean = false,
    fieldModifier: Modifier = Modifier,
    /** Entered once and kept by the server (Q94): read-only, a lock on the right, the hint says who can change it. */
    locked: Boolean = false,
) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(ElchiShape.field)
    @Suppress("NAME_SHADOWING") val enabled = enabled && !locked
    val errorColors = c.tone(Tone.ERR)
    val textStyle = if (monospace) Elchi.type.body.copy(fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace) else Elchi.type.body
    // The whole rounded box is the touch target, not only the line of text inside it (a tall comment field).
    val focus = remember { androidx.compose.ui.focus.FocusRequester() }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        if (label != null) Text(label, style = Elchi.type.label, color = c.text)
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = minHeight)
                .clip(shape)
                .background(if (locked) (if (c.isDark) Color(0xFF22262D) else Color(0xFFE9EDF2)) else c.field)
                .then(if (error != null) Modifier.border(1.5.dp, errorColors.fg, shape) else Modifier)
                .alpha(if (locked) 0.8f else if (enabled) 1f else 0.6f)
                .clickable(remember { MutableInteractionSource() }, indication = null, enabled = enabled) { focus.requestFocus() }
                .padding(horizontal = 16.dp),
            verticalAlignment = if (singleLine) Alignment.CenterVertically else Alignment.Top,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (icon != null) ElchiIconView(icon, c.muted, size = 18.dp)
            if (prefix != null) {
                Text(prefix, style = Elchi.type.bodyStrong, color = c.text)
                Spacer(Modifier.width(1.dp).height(22.dp).background(c.outline))
            }
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                enabled = enabled,
                singleLine = singleLine,
                textStyle = textStyle.copy(color = c.text),
                cursorBrush = SolidColor(c.brand),
                keyboardOptions = keyboardOptions,
                keyboardActions = keyboardActions,
                visualTransformation = visualTransformation,
                modifier = Modifier.weight(1f).padding(vertical = 14.dp).focusRequester(focus).then(fieldModifier),
                // The placeholder sits in the same box as the text, so both share one baseline.
                decorationBox = { inner ->
                    Box(contentAlignment = if (singleLine) Alignment.CenterStart else Alignment.TopStart) {
                        if (value.isEmpty() && placeholder != null) Text(placeholder, style = textStyle, color = c.placeholder, maxLines = if (singleLine) 1 else Int.MAX_VALUE)
                        inner()
                    }
                },
            )
            if (locked) ElchiIconView(ElchiIcon.LOCK, c.placeholder, size = 18.dp)
        }
        val below = error ?: hint
        if (below != null) Text(below, style = Elchi.type.caption, color = if (error != null) errorColors.fg else c.muted)
    }
}

/** Segmented control (pill track, the selected segment raised on a card). */
@Composable
fun <T> Segmented(options: List<Pair<T, String>>, selected: T, onSelect: (T) -> Unit, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    Row(modifier.fillMaxWidth().clip(CircleShape).background(c.field).padding(4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        options.forEach { (value, label) ->
            val active = value == selected
            Box(
                Modifier
                    .weight(1f)
                    .height(38.dp)
                    .then(if (active) Modifier.shadow(4.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow) else Modifier)
                    .clip(CircleShape)
                    .background(if (active) c.card else Color.Transparent)
                    .selectable(active, role = Role.Tab) { onSelect(value) },
                contentAlignment = Alignment.Center,
            ) { Text(label, style = Elchi.type.buttonSmall, color = if (active) c.text else c.muted, maxLines = 1) }
        }
    }
}

/**
 * A pill choice. [filled] is the prototype's `chips` block (selected = brand fill, navy text: sort and TTL chips);
 * without it the selected chip is the soft blue of a toggled filter (stop chips).
 */
@Composable
fun Chip(text: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier, icon: ElchiIcon? = null, filled: Boolean = false) {
    val c = Elchi.colors
    val bg = if (selected) (if (filled) c.brand else c.soft) else c.card
    val fg = if (selected) (if (filled) c.onBrand else c.softText) else c.text
    Row(
        modifier
            .clip(CircleShape)
            .background(bg)
            .border(1.dp, if (selected) Color.Transparent else c.line, CircleShape)
            .selectable(selected, role = Role.Checkbox, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (icon != null) ElchiIconView(icon, fg, size = 14.dp)
        Text(text, style = Elchi.type.label, color = fg)
    }
}

/** A setting on its own card: title, one-line explanation, switch. */
@Composable
fun ToggleRow(title: String, description: String, checked: Boolean, onChange: (Boolean) -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    val c = Elchi.colors
    ElchiCard(modifier.toggleable(value = checked, enabled = enabled, role = Role.Switch, onValueChange = onChange), padding = PaddingValues(horizontal = 16.dp, vertical = 14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(title, style = Elchi.type.secondary.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold), color = c.text)
                Text(description, style = Elchi.type.caption, color = c.muted)
            }
            Box(
                // The whole switch fades when disabled (the prototype's `op`); the alpha sits before the track so the track is
                // inside the same layer as the knob.
                Modifier.width(52.dp).height(30.dp).alpha(if (enabled) 1f else 0.5f).clip(CircleShape).background(if (checked) c.brand else c.outline).padding(3.dp),
                contentAlignment = if (checked) Alignment.CenterEnd else Alignment.CenterStart,
            ) { Box(Modifier.size(24.dp).shadow(1.dp, CircleShape).clip(CircleShape).background(Color.White)) }
        }
    }
}

/**
 * One circle per OTP digit (the prototype's `otp` block): empty = outline, filled = brand ring on a soft fill,
 * next = thicker brand ring, error = red on red tint. Input goes to a hidden field (see OtpScreen).
 */
@Composable
fun OtpCells(code: String, length: Int, modifier: Modifier = Modifier, error: Boolean = false) {
    val c = Elchi.colors
    val err = c.tone(Tone.ERR)
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(14.dp, Alignment.CenterHorizontally)) {
        repeat(length) { i ->
            val digit = code.getOrNull(i)?.toString() ?: ""
            val (borderWidth, border, bg) = when {
                error -> Triple(2.dp, err.fg, err.bg)
                i == code.length -> Triple(2.5.dp, c.brand, c.card)
                digit.isNotEmpty() -> Triple(2.dp, c.brand, if (c.isDark) Color(0xFF0E2A45) else Color(0xFFEAF5FF))
                else -> Triple(1.5.dp, c.outline, c.card)
            }
            Box(
                Modifier.size(60.dp).clip(CircleShape).background(bg).border(borderWidth, border, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    digit,
                    style = Elchi.type.title.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold),
                    color = if (error) err.fg else c.text,
                )
            }
        }
    }
}

/**
 * Who decides the status/navigation bar icon colour. Screens push a request while they are on screen and remove
 * only their own on leaving, so during a transition the newest screen wins whatever order enter/leave run in.
 */
class SystemBarIconsController {
    private class Request(val dark: Boolean)

    private val requests = androidx.compose.runtime.mutableStateListOf<Request>()
    val dark: Boolean? get() = requests.lastOrNull()?.dark

    internal fun push(dark: Boolean): () -> Unit {
        val request = Request(dark)
        requests.add(request)
        return { requests.remove(request) }
    }
}

val LocalSystemBarIcons = androidx.compose.runtime.staticCompositionLocalOf { SystemBarIconsController() }

/** Applies the controller's current request to the window (place once, at the root). */
@Composable
fun SystemBarIconsHost(controller: SystemBarIconsController, fallbackDark: Boolean) {
    val view = androidx.compose.ui.platform.LocalView.current
    val dark = controller.dark ?: fallbackDark
    androidx.compose.runtime.LaunchedEffect(dark) {
        val window = (view.context as? android.app.Activity)?.window ?: return@LaunchedEffect
        androidx.core.view.WindowCompat.getInsetsController(window, view).apply {
            isAppearanceLightStatusBars = dark
            isAppearanceLightNavigationBars = dark
        }
    }
}

/** Dark (true) or light bar icons for as long as the caller is on screen. The navy splash asks for light ones. */
@Composable
fun SystemBarIcons(dark: Boolean) {
    val controller = LocalSystemBarIcons.current
    androidx.compose.runtime.DisposableEffect(controller, dark) {
        val remove = controller.push(dark)
        onDispose(remove)
    }
}

/** Screen top bar from the prototype: floating back button, optional logo on the right. */
@Composable
fun TopBar(onBack: (() -> Unit)?, backLabel: String, modifier: Modifier = Modifier, logo: Boolean = false) {
    Row(
        modifier.fillMaxWidth().height(58.dp).padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (onBack != null) RoundIconButton(ElchiIcon.BACK, backLabel, onBack)
        Spacer(Modifier.weight(1f))
        if (logo) ElchiLogo(height = 24.dp)
    }
}

@Composable
fun ElchiLogo(height: Dp, modifier: Modifier = Modifier) {
    androidx.compose.foundation.Image(
        painterResource(uz.elchi.app.R.drawable.elchi_logo),
        contentDescription = "elchi",
        modifier = modifier.height(height),
        contentScale = androidx.compose.ui.layout.ContentScale.FillHeight,
    )
}

/** Full-width status strip under the top bar ("Kod yuborildi", "Kod noto'g'ri"). Announced to TalkBack. */
@Composable
fun Banner(text: String, tone: Tone, modifier: Modifier = Modifier) {
    val colors = Elchi.colors.tone(tone)
    Text(
        text,
        modifier
            .fillMaxWidth()
            .background(colors.bg)
            .padding(horizontal = 16.dp, vertical = 9.dp)
            .semantics { liveRegion = androidx.compose.ui.semantics.LiveRegionMode.Polite },
        style = Elchi.type.label.copy(fontSize = androidx.compose.ui.unit.TextUnit(12.5f, androidx.compose.ui.unit.TextUnitType.Sp)),
        color = colors.fg,
    )
}

/** A large choice card (role screen): tinted icon tile, title, one line, chevron. */
@Composable
fun ChoiceCard(icon: ElchiIcon, title: String, description: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(24.dp)
    Row(
        modifier
            .fillMaxWidth()
            .shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(shape)
            .background(c.card)
            .border(1.dp, c.line, shape)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(18.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Box(Modifier.size(56.dp).clip(RoundedCornerShape(18.dp)).background(c.soft), contentAlignment = Alignment.Center) {
            ElchiIconView(icon, c.accentText, size = 26.dp)
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = Elchi.type.section.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold), color = c.text)
            Text(description, style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.Normal), color = c.muted)
        }
        ElchiIconView(ElchiIcon.CHEV_R, c.placeholder, size = 18.dp)
    }
}

/** Page dots: the current one stretches to a bar (the prototype's onboarding dots). */
@Composable
fun PageDots(count: Int, current: Int, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        repeat(count) { i ->
            Box(Modifier.width(if (i == current) 24.dp else 8.dp).height(8.dp).clip(CircleShape).background(if (i == current) c.brand else c.outline))
        }
    }
}

/** Screen body padding used across the prototype (16dp sides). */
val ScreenPadding = PaddingValues(horizontal = 16.dp)

// -- Stage 02 blocks (the prototype's route, list, grid3, radio, upload, empty) ----------------------------------

/**
 * Screen title bar (`top: 'bar'`): floating back button, title, optional right-hand note (the chosen region) or
 * action ([onRight]: "Takliflarim", "Yangilash"). [leadingIcon] MENU makes it the `hamb` bar of a drawer screen.
 */
@Composable
fun TitleBar(
    onBack: (() -> Unit)?,
    backLabel: String,
    title: String,
    modifier: Modifier = Modifier,
    right: String? = null,
    onRight: (() -> Unit)? = null,
    leadingIcon: ElchiIcon = ElchiIcon.BACK,
    leadingDot: Boolean = false,
) {
    Row(
        modifier.fillMaxWidth().height(64.dp).padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (onBack != null) RoundIconButton(leadingIcon, backLabel, onBack, dot = leadingDot)
        Text(
            title,
            Modifier.weight(1f).semantics { heading() },
            style = Elchi.type.section.copy(fontSize = androidx.compose.ui.unit.TextUnit(18f, androidx.compose.ui.unit.TextUnitType.Sp)),
            color = Elchi.colors.text,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (right != null) {
            Box(
                Modifier.heightIn(min = 44.dp).then(if (onRight != null) Modifier.clip(CircleShape).clickable(role = Role.Button, onClick = onRight).padding(horizontal = 6.dp) else Modifier),
                contentAlignment = Alignment.Center,
            ) {
                Text(right, style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold), color = Elchi.colors.accentText, maxLines = 1)
            }
        }
    }
}

/**
 * A read-only field that opens a picker (date, time): same look as [ElchiField], trailing icon, one tap target.
 * [placeholder] shows the expected shape ("kk.oo.yyyy, --:--") when there is no value.
 */
@Composable
fun PickerField(
    label: String,
    value: String?,
    placeholder: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    trailingIcon: ElchiIcon = ElchiIcon.CLOCK,
    hint: String? = null,
    error: Boolean = false,
) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(ElchiShape.field)
    val err = c.tone(Tone.ERR)
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, style = Elchi.type.label, color = c.text)
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 52.dp)
                .clip(shape)
                .background(if (error && !c.isDark) Color(0xFFFFF6F6) else c.field)
                .then(if (error) Modifier.border(1.5.dp, err.fg, shape) else Modifier)
                .clickable(role = Role.Button, onClick = onClick)
                .semantics { contentDescription = "$label: ${value ?: placeholder}" }
                .padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(value ?: placeholder, Modifier.weight(1f), style = Elchi.type.body, color = if (value == null) c.placeholder else c.text)
            ElchiIconView(trailingIcon, c.muted, size = 18.dp)
        }
        if (hint != null) Text(hint, style = Elchi.type.caption, color = c.muted)
    }
}

/**
 * The route card: origin ring and destination pin joined by a dashed line, each row a button that opens the
 * place picker. An empty end shows its question ("Qayerdan?") in the placeholder colour.
 */
@Composable
fun RouteCard(
    from: String?,
    fromDetail: String?,
    to: String?,
    toDetail: String?,
    fromPlaceholder: String,
    toPlaceholder: String,
    onFrom: () -> Unit,
    onTo: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val c = Elchi.colors
    val dash = c.outline
    ElchiCard(modifier, padding = PaddingValues(0.dp)) {
        Box {
            // Dashed connector between the two glyphs (decorative).
            androidx.compose.foundation.Canvas(Modifier.matchParentSize().padding(start = 22.dp, top = 38.dp, bottom = 38.dp)) {
                drawLine(
                    dash,
                    androidx.compose.ui.geometry.Offset(1.dp.toPx(), 0f),
                    androidx.compose.ui.geometry.Offset(1.dp.toPx(), size.height),
                    strokeWidth = 2.dp.toPx(),
                    pathEffect = androidx.compose.ui.graphics.PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 4.dp.toPx())),
                )
            }
            Column {
                RouteRow(from, fromDetail, fromPlaceholder, onFrom) {
                    Box(Modifier.size(14.dp).clip(CircleShape).background(c.card).border(3.dp, c.brand, CircleShape))
                }
                Spacer(Modifier.padding(start = 44.dp).fillMaxWidth().height(1.dp).background(c.field))
                RouteRow(to, toDetail, toPlaceholder, onTo) {
                    Box(
                        Modifier
                            .padding(start = 1.dp)
                            .size(13.dp)
                            .graphicsLayer { rotationZ = -45f }
                            .clip(RoundedCornerShape(topStart = 7.dp, topEnd = 7.dp, bottomEnd = 7.dp, bottomStart = 0.dp))
                            .background(c.pin),
                    )
                }
            }
        }
    }
}

@Composable
private fun RouteRow(value: String?, detail: String?, placeholder: String, onClick: () -> Unit, glyph: @Composable () -> Unit) {
    val c = Elchi.colors
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Box(Modifier.size(14.dp), contentAlignment = Alignment.Center) { glyph() }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(value ?: placeholder, style = Elchi.type.bodyStrong, color = if (value == null) c.placeholder else c.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (value != null && detail != null) Text(detail, style = Elchi.type.caption, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        ElchiIconView(ElchiIcon.CHEV_R, c.placeholder, size = 18.dp)
    }
}

/** White rounded list (the prototype's `list` block); put [ListRow]s inside. */
@Composable
fun ListCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    ElchiCard(modifier, padding = PaddingValues(vertical = 4.dp), content = content)
}

enum class ListRowStyle { NORMAL, CURRENT, DANGER }

/**
 * A list row: optional round icon, title, one-line description, chevron. [onClick] null makes it inert (a "later"
 * item); [badge] then says why under the description, so the state is not only a grey colour.
 */
@Composable
fun ListRow(
    title: String,
    modifier: Modifier = Modifier,
    icon: ElchiIcon? = null,
    description: String? = null,
    first: Boolean = false,
    style: ListRowStyle = ListRowStyle.NORMAL,
    badge: String? = null,
    chevron: Boolean = true,
    /** A red count pill on the right (unread notifications); null or 0 = none. */
    count: String? = null,
    onClick: (() -> Unit)? = null,
) {
    val c = Elchi.colors
    val err = c.tone(Tone.ERR)
    val (iconBg, iconFg) = when (style) {
        ListRowStyle.CURRENT -> c.brand to c.onBrand
        ListRowStyle.DANGER -> err.bg to err.fg
        ListRowStyle.NORMAL -> (if (c.isDark) c.field else Color(0xFFEEF4FA)) to c.accentText
    }
    Column(modifier) {
        if (!first) Spacer(Modifier.fillMaxWidth().height(1.dp).background(c.field))
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = if (description != null) 64.dp else 52.dp)
                .background(if (style == ListRowStyle.CURRENT) c.highlight else Color.Transparent)
                .then(if (onClick != null) Modifier.clickable(role = Role.Button, onClick = onClick) else Modifier)
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (icon != null) {
                Box(Modifier.size(38.dp).clip(CircleShape).background(iconBg), contentAlignment = Alignment.Center) { ElchiIconView(icon, iconFg, size = 18.dp) }
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
                Text(
                    title,
                    style = Elchi.type.secondary.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold),
                    color = if (style == ListRowStyle.DANGER) err.fg else if (onClick == null && badge != null) c.muted else c.text,
                )
                if (description != null) Text(description, style = Elchi.type.caption, color = c.muted)
                if (badge != null) Badge(badge, Tone.GRAY, Modifier.padding(top = 4.dp))
            }
            // The count takes the chevron's place, so a long title ("Bildirishnomalar") keeps its one line.
            if (count != null) {
                Text(count, Modifier.clip(CircleShape).background(err.fg).padding(horizontal = 7.dp, vertical = 2.dp), style = Elchi.type.badge, color = if (c.isDark) Color(0xFF17191E) else Color.White, maxLines = 1)
            } else if (chevron && onClick != null && style != ListRowStyle.DANGER) {
                ElchiIconView(ElchiIcon.CHEV_R, c.placeholder, size = 16.dp)
            }
        }
    }
}

/** Three-column choice tiles (the prototype's `grid3`): one selected, brand filled. */
@Composable
fun <T> ChoiceGrid(options: List<Pair<T, String>>, selected: T?, onSelect: (T) -> Unit, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        options.chunked(3).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { (value, label) ->
                    val active = value == selected
                    Box(
                        Modifier
                            .weight(1f)
                            .height(44.dp)
                            .clip(RoundedCornerShape(14.dp))
                            .background(if (active) c.brand else c.field)
                            .selectable(active, role = Role.RadioButton) { onSelect(value) },
                        contentAlignment = Alignment.Center,
                    ) { Text(label, style = Elchi.type.label, color = if (active) c.onBrand else c.text, maxLines = 1, overflow = TextOverflow.Ellipsis) }
                }
                repeat(3 - row.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

/** A radio option card (the prototype's `radio`): icon tile, title, one line, radio circle. */
@Composable
fun RadioCard(icon: ElchiIcon, title: String, description: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(16.dp)
    Row(
        modifier
            .fillMaxWidth()
            .clip(shape)
            .background(if (selected) c.highlight else c.card)
            .border(if (selected) 2.dp else 1.dp, if (selected) c.brand else c.line, shape)
            .selectable(selected, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(c.card).border(1.dp, c.line, RoundedCornerShape(12.dp)), contentAlignment = Alignment.Center) {
            ElchiIconView(icon, c.accentText)
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(title, style = Elchi.type.secondary.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold), color = c.text)
            Text(description, style = Elchi.type.caption, color = c.muted)
        }
        Box(Modifier.size(20.dp).clip(CircleShape).border(if (selected) 6.dp else 2.dp, if (selected) c.brand else c.outline, CircleShape))
    }
}

/** Dashed upload target (the prototype's `upload`). */
@Composable
fun UploadBox(title: String, description: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(ElchiShape.card)
    Column(
        modifier
            .fillMaxWidth()
            .clip(shape)
            .background(if (c.isDark) c.highlight else Color(0xFFF4FAFF))
            .drawBehind {
                val stroke = 2.dp.toPx()
                drawRoundRect(
                    color = c.brand,
                    topLeft = androidx.compose.ui.geometry.Offset(stroke / 2, stroke / 2),
                    size = androidx.compose.ui.geometry.Size(size.width - stroke, size.height - stroke),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(ElchiShape.card.toPx()),
                    style = androidx.compose.ui.graphics.drawscope.Stroke(stroke, pathEffect = androidx.compose.ui.graphics.PathEffect.dashPathEffect(floatArrayOf(7.dp.toPx(), 5.dp.toPx()))),
                )
            }
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 30.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(Modifier.size(56.dp).clip(CircleShape).background(c.soft), contentAlignment = Alignment.Center) { ElchiIconView(ElchiIcon.UPLOAD, c.accentText, size = 24.dp) }
        Text(title, style = Elchi.type.bodyStrong, color = c.text)
        Text(description, Modifier.widthIn(max = 260.dp), style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.Normal), color = c.muted, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
    }
}

/** Centred icon, title and text (the prototype's `empty`, also its success block). */
@Composable
fun EmptyState(icon: ElchiIcon, title: String, modifier: Modifier = Modifier, description: String? = null) {
    val c = Elchi.colors
    Column(modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(Modifier.size(64.dp).clip(CircleShape).background(if (c.isDark) c.field else Color(0xFFE4E9EF)), contentAlignment = Alignment.Center) {
            ElchiIconView(icon, c.muted, size = 28.dp)
        }
        Text(title, Modifier.semantics { heading() }, style = Elchi.type.section.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold), color = c.text, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        if (description != null) Text(description, Modifier.widthIn(max = 280.dp), style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.Normal, lineHeight = androidx.compose.ui.unit.TextUnit(19.5f, androidx.compose.ui.unit.TextUnitType.Sp)), color = c.muted, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
    }
}

// -- Stage 03 blocks (the prototype's item, money, check) --------------------------------------------------------

/** A line under an [ItemCard]'s title; [color] null = the muted default (the countdown is warn-coloured). */
data class ItemLine(val text: String, val color: Color? = null)

/**
 * The prototype's `item` card (an order, a listing, an offer): title with an optional icon and status badge,
 * a sub-line, small lines, and a footer with a meta text and the price on the right. [underlined] is the offer
 * card's brand rule under "Haydovchi #N"; [highlighted] its 2dp brand border (the cheapest offer). [footer] holds
 * an in-card action (withdraw).
 */
@Composable
fun ItemCard(
    title: String,
    modifier: Modifier = Modifier,
    icon: ElchiIcon? = null,
    badge: Pair<String, Tone>? = null,
    sub: String? = null,
    lines: List<ItemLine> = emptyList(),
    meta: String? = null,
    right: String? = null,
    rightColor: Color? = null,
    highlighted: Boolean = false,
    underlined: Boolean = false,
    onClick: (() -> Unit)? = null,
    footer: (@Composable ColumnScope.() -> Unit)? = null,
) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(ElchiShape.card)
    Column(
        modifier
            .fillMaxWidth()
            .shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(shape)
            .background(c.card)
            .then(if (highlighted) Modifier.border(2.dp, c.brand, shape) else Modifier)
            .then(if (onClick != null) Modifier.clickable(role = Role.Button, onClick = onClick) else Modifier)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(
            Modifier.fillMaxWidth().then(
                if (underlined) Modifier.drawBehind {
                    val stroke = 1.5.dp.toPx()
                    drawLine(c.brand, androidx.compose.ui.geometry.Offset(0f, size.height - stroke / 2), androidx.compose.ui.geometry.Offset(size.width, size.height - stroke / 2), stroke)
                }.padding(bottom = 10.dp) else Modifier,
            ),
            verticalAlignment = Alignment.Top,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (icon != null) ElchiIconView(icon, c.accentText, size = 16.dp)
                Text(title, style = Elchi.type.bodyStrong.copy(lineHeight = androidx.compose.ui.unit.TextUnit(19.5f, androidx.compose.ui.unit.TextUnitType.Sp)), color = c.text)
            }
            if (badge != null) Badge(badge.first, badge.second)
        }
        if (sub != null) Text(sub, style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.Normal), color = c.muted)
        lines.forEach { line -> Text(line.text, style = Elchi.type.caption, color = line.color ?: c.muted) }
        if (meta != null || right != null) {
            Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(meta.orEmpty(), Modifier.weight(1f), style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.Normal), color = c.muted)
                if (right != null) Text(right, style = Elchi.type.section.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold), color = rightColor ?: c.text, maxLines = 1)
            }
        }
        if (footer != null) Column(Modifier.padding(top = 6.dp), verticalArrangement = Arrangement.spacedBy(8.dp), content = footer)
    }
}

/** A row of the money block: [strong] rows (the total) get a hairline above and semibold text. */
data class MoneyRow(val key: String, val value: String, val strong: Boolean = false, val color: Color? = null)

/**
 * The prototype's `money` block: grey rounded panel of amounts ("Taklif narxi / Bonus chegirmasi / Haydovchiga naqd
 * to'lanadi"), optionally with the unticked consent box under them ([check] text + state).
 */
@Composable
fun MoneyBlock(rows: List<MoneyRow>, modifier: Modifier = Modifier, check: String? = null, checked: Boolean = false, onCheck: ((Boolean) -> Unit)? = null) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(16.dp)
    Column(modifier.fillMaxWidth().clip(shape).background(c.page).border(1.dp, c.line, shape).padding(horizontal = 14.dp, vertical = 6.dp)) {
        rows.forEachIndexed { i, row ->
            if (i > 0 && row.strong) Spacer(Modifier.fillMaxWidth().height(1.dp).background(c.line))
            Row(Modifier.fillMaxWidth().padding(vertical = 7.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                val weight = if (row.strong) androidx.compose.ui.text.font.FontWeight.SemiBold else androidx.compose.ui.text.font.FontWeight.Normal
                Text(row.key, Modifier.weight(1f), style = Elchi.type.label.copy(fontWeight = weight), color = row.color ?: c.text)
                Text(row.value, style = Elchi.type.label.copy(fontWeight = weight), color = row.color ?: c.text, maxLines = 1)
            }
        }
        if (check != null && onCheck != null) {
            Spacer(Modifier.fillMaxWidth().height(1.dp).background(c.line))
            CheckRow(check, checked, onCheck, Modifier.padding(vertical = 4.dp))
        }
    }
}

/** A checkbox with its sentence; the whole row is the (44dp) touch target. */
@Composable
fun CheckRow(text: String, checked: Boolean, onChange: (Boolean) -> Unit, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    Row(
        modifier.fillMaxWidth().heightIn(min = 44.dp).toggleable(value = checked, role = Role.Checkbox, onValueChange = onChange),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(
            Modifier.size(20.dp).clip(RoundedCornerShape(6.dp)).background(if (checked) c.brand else c.card).border(2.dp, if (checked) c.brand else c.outline, RoundedCornerShape(6.dp)),
            contentAlignment = Alignment.Center,
        ) { if (checked) ElchiIconView(ElchiIcon.CHECK, c.onBrand, size = 14.dp) }
        Text(text, Modifier.weight(1f), style = Elchi.type.label, color = c.text)
    }
}

// -- Stage 04 blocks (the prototype's steps, gps, chat, composer, stars, select) ----------------------------------

/** A rung of [StatusLadder]: done (green), current (brand), or still ahead (hollow, grey text). */
enum class LadderState { DONE, CURRENT, TODO }

data class LadderRow(val title: String, val time: String?, val state: LadderState)

/**
 * The prototype's `steps` card: a vertical ladder of dots joined by a line that is green up to the last done rung.
 * The state is also in the text weight and in TalkBack's description, not only in the colour.
 */
@Composable
fun StatusLadder(rows: List<LadderRow>, modifier: Modifier = Modifier, stateLabels: Map<LadderState, String> = emptyMap()) {
    val c = Elchi.colors
    val ok = c.tone(Tone.OK).fg
    ElchiCard(modifier, padding = PaddingValues(16.dp)) {
        rows.forEachIndexed { i, row ->
            val reached = row.state != LadderState.TODO
            Row(
                Modifier.fillMaxWidth().height(androidx.compose.foundation.layout.IntrinsicSize.Min)
                    .semantics(mergeDescendants = true) { stateLabels[row.state]?.let { stateDescription = it } },
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Column(Modifier.width(14.dp).fillMaxHeight(), horizontalAlignment = Alignment.CenterHorizontally) {
                    Box(
                        Modifier.size(14.dp).clip(CircleShape)
                            .background(when (row.state) { LadderState.DONE -> ok; LadderState.CURRENT -> c.brand; LadderState.TODO -> c.card })
                            .then(if (row.state == LadderState.TODO) Modifier.border(2.dp, c.outline, CircleShape) else Modifier),
                    )
                    if (i != rows.lastIndex) Box(Modifier.width(2.dp).weight(1f).heightIn(min = 20.dp).background(if (row.state == LadderState.DONE) ok else c.line))
                }
                Column(Modifier.weight(1f).padding(bottom = if (i == rows.lastIndex) 0.dp else 14.dp).offset(y = (-3).dp), verticalArrangement = Arrangement.spacedBy(1.dp)) {
                    Text(
                        row.title,
                        style = Elchi.type.secondary.copy(fontWeight = if (reached) androidx.compose.ui.text.font.FontWeight.SemiBold else androidx.compose.ui.text.font.FontWeight.Medium),
                        color = if (reached) c.text else c.placeholder,
                    )
                    if (row.time != null) Text(row.time, style = Elchi.type.caption, color = c.muted)
                }
            }
        }
    }
}

/** The four live-location states of the prototype's `gps` block. */
enum class GpsTone { LIVE, DELAYED, LOST, NONE }

/**
 * One live-location state line: a dot (with a halo only when the position is really live), the state, and its
 * explanation lines. The word carries the state; the dot is only a second signal.
 */
@Composable
fun GpsStateRow(tone: GpsTone, title: String, notes: List<String>, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    val dot = when (tone) {
        GpsTone.LIVE -> c.tone(Tone.OK).fg
        GpsTone.DELAYED -> Color(0xFFE0A100)
        GpsTone.LOST -> c.danger
        GpsTone.NONE -> Color(0xFF9AA6B5)
    }
    Row(
        modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(c.card).border(1.dp, c.line, RoundedCornerShape(14.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp)
            .semantics(mergeDescendants = true) { liveRegion = androidx.compose.ui.semantics.LiveRegionMode.Polite },
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(Modifier.padding(top = 4.dp).size(if (tone == GpsTone.LIVE) 18.dp else 10.dp), contentAlignment = Alignment.Center) {
            if (tone == GpsTone.LIVE) Box(Modifier.size(18.dp).clip(CircleShape).background(dot.copy(alpha = 0.2f)))
            Box(Modifier.size(10.dp).clip(CircleShape).background(dot))
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold), color = c.text)
            notes.forEach { Text(it, style = Elchi.type.caption.copy(fontSize = androidx.compose.ui.unit.TextUnit(11.5f, androidx.compose.ui.unit.TextUnitType.Sp)), color = c.muted) }
        }
    }
}

/** Who a chat bubble belongs to (the prototype's `chat` block kinds). */
enum class BubbleKind { MINE, THEIRS, OPERATOR, SYSTEM, HIDDEN }

/**
 * A chat bubble: own messages right on the brand fill, the other side left on a card with its label above,
 * operator messages with a brand border, hidden ones grey italic, system lines centred and small. [footer] is an
 * action row under a bubble (the failed send's "Qayta urinish").
 */
@Composable
fun ChatBubble(
    kind: BubbleKind,
    text: String,
    modifier: Modifier = Modifier,
    label: String? = null,
    time: String? = null,
    footer: (@Composable () -> Unit)? = null,
) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(18.dp)
    val align = when (kind) {
        BubbleKind.MINE -> Alignment.End
        BubbleKind.SYSTEM -> Alignment.CenterHorizontally
        else -> Alignment.Start
    }
    Column(modifier.fillMaxWidth(), horizontalAlignment = align, verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Column(Modifier.fillMaxWidth(if (kind == BubbleKind.SYSTEM) 1f else 0.8f).semantics(mergeDescendants = true) {}, horizontalAlignment = align, verticalArrangement = Arrangement.spacedBy(3.dp)) {
            if (label != null) Text(label, style = Elchi.type.badge, color = c.accentText)
            val (bg, fg) = when (kind) {
                BubbleKind.MINE -> c.brand to c.onBrand
                BubbleKind.THEIRS, BubbleKind.OPERATOR -> c.card to c.text
                BubbleKind.HIDDEN -> c.field to c.muted
                BubbleKind.SYSTEM -> Color.Transparent to c.muted
            }
            Text(
                text,
                Modifier
                    .clip(shape)
                    .background(bg)
                    .then(
                        when (kind) {
                            BubbleKind.THEIRS -> Modifier.border(1.dp, c.line, shape)
                            BubbleKind.OPERATOR -> Modifier.border(1.5.dp, c.brand, shape)
                            else -> Modifier
                        },
                    )
                    .padding(if (kind == BubbleKind.SYSTEM) PaddingValues(horizontal = 8.dp, vertical = 2.dp) else PaddingValues(horizontal = 14.dp, vertical = 10.dp)),
                style = if (kind == BubbleKind.SYSTEM) Elchi.type.caption
                else Elchi.type.label.copy(
                    fontSize = androidx.compose.ui.unit.TextUnit(13.5f, androidx.compose.ui.unit.TextUnitType.Sp),
                    lineHeight = androidx.compose.ui.unit.TextUnit(19.5f, androidx.compose.ui.unit.TextUnitType.Sp),
                    fontWeight = androidx.compose.ui.text.font.FontWeight.Normal,
                    fontStyle = if (kind == BubbleKind.HIDDEN) androidx.compose.ui.text.font.FontStyle.Italic else androidx.compose.ui.text.font.FontStyle.Normal,
                ),
                color = fg,
                textAlign = if (kind == BubbleKind.SYSTEM) androidx.compose.ui.text.style.TextAlign.Center else null,
            )
            if (time != null) Text(time, style = Elchi.type.caption.copy(fontSize = androidx.compose.ui.unit.TextUnit(11f, androidx.compose.ui.unit.TextUnitType.Sp)), color = c.placeholder)
        }
        footer?.invoke()
    }
}

/**
 * The prototype's `composer`: quick-reply chips, a pill text field and the round send button, and one hint line
 * under them. [chips] empty = no chip row (the operator chat).
 */
@Composable
fun Composer(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    sendLabel: String,
    onSend: () -> Unit,
    modifier: Modifier = Modifier,
    chips: List<Pair<String, () -> Unit>> = emptyList(),
    hint: String? = null,
    enabled: Boolean = true,
    sending: Boolean = false,
) {
    val c = Elchi.colors
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (chips.isNotEmpty()) {
            Row(Modifier.horizontalScroll(androidx.compose.foundation.rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                chips.forEach { (text, onClick) ->
                    Text(
                        text,
                        Modifier
                            .heightIn(min = 36.dp)
                            .clip(CircleShape)
                            .background(c.soft)
                            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
                            .padding(horizontal = 14.dp, vertical = 8.dp),
                        style = Elchi.type.label,
                        color = c.softText,
                        maxLines = 1,
                    )
                }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                enabled = enabled,
                textStyle = Elchi.type.secondary.copy(color = c.text),
                cursorBrush = SolidColor(c.brand),
                keyboardOptions = KeyboardOptions(capitalization = androidx.compose.ui.text.input.KeyboardCapitalization.Sentences),
                maxLines = 4,
                modifier = Modifier.weight(1f).heightIn(min = 48.dp).clip(RoundedCornerShape(24.dp)).background(c.field).padding(horizontal = 18.dp, vertical = 13.dp),
                decorationBox = { inner ->
                    Box(contentAlignment = Alignment.CenterStart) {
                        if (value.isEmpty()) Text(placeholder, style = Elchi.type.secondary, color = c.placeholder, maxLines = 1)
                        inner()
                    }
                },
            )
            val canSend = enabled && value.isNotBlank() && !sending
            Box(
                Modifier
                    .size(48.dp)
                    .clip(CircleShape)
                    .background(if (canSend) c.brand else c.field)
                    .clickable(enabled = canSend, role = Role.Button, onClick = onSend)
                    .semantics { contentDescription = sendLabel },
                contentAlignment = Alignment.Center,
            ) {
                if (sending) CircularProgressIndicator(Modifier.size(20.dp), color = c.onBrand, strokeWidth = 2.dp)
                else ElchiIconView(ElchiIcon.SEND, if (canSend) c.onBrand else c.placeholder, size = 20.dp)
            }
        }
        if (hint != null) Text(hint, style = Elchi.type.caption.copy(fontSize = androidx.compose.ui.unit.TextUnit(11f, androidx.compose.ui.unit.TextUnitType.Sp)), color = c.muted)
    }
}

/** Five tappable stars (the prototype's `stars`, 40dp each, 48dp touch targets). [label] names a value for TalkBack. */
@Composable
fun StarRating(value: Int, onChange: (Int) -> Unit, label: (Int) -> String, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    val off = if (c.isDark) c.outline else Color(0xFFD5DCE5)
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(2.dp, Alignment.CenterHorizontally)) {
        (1..5).forEach { n ->
            Box(
                Modifier
                    .size(48.dp)
                    .selectable(selected = n == value, role = Role.RadioButton) { onChange(n) }
                    .semantics { contentDescription = label(n) },
                contentAlignment = Alignment.Center,
            ) {
                val fill = if (n <= value) c.brand else off
                androidx.compose.foundation.Canvas(Modifier.size(40.dp)) {
                    val cx = size.width / 2
                    val cy = size.height / 2
                    val outer = size.minDimension / 2
                    val inner = outer * 0.45f
                    val path = androidx.compose.ui.graphics.Path()
                    for (k in 0 until 10) {
                        val r = if (k % 2 == 0) outer else inner
                        val a = Math.toRadians(-90.0 + k * 36.0)
                        val x = cx + (r * kotlin.math.cos(a)).toFloat()
                        val y = cy + (r * kotlin.math.sin(a)).toFloat() + outer * 0.06f
                        if (k == 0) path.moveTo(x, y) else path.lineTo(x, y)
                    }
                    path.close()
                    drawPath(path, fill)
                }
            }
        }
    }
}

/**
 * A select field (`field` with `sel`): shows the choice with a chevron; a tap unfolds the options right under it
 * (no second window over a sheet). [value] null shows [placeholder].
 */
@Composable
fun <T> SelectField(
    label: String,
    value: T?,
    options: List<Pair<T, String>>,
    onSelect: (T) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    hint: String? = null,
) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(ElchiShape.field)
    var open by androidx.compose.runtime.saveable.rememberSaveable { androidx.compose.runtime.mutableStateOf(false) }
    val current = options.firstOrNull { it.first == value }?.second
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, style = Elchi.type.label, color = c.text)
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 52.dp)
                .clip(shape)
                .background(c.field)
                .clickable(role = Role.DropdownList) { open = !open }
                .semantics { contentDescription = "$label: ${current ?: placeholder}" }
                .padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(current ?: placeholder, Modifier.weight(1f), style = Elchi.type.body, color = if (current == null) c.placeholder else c.text)
            ElchiIconView(if (open) ElchiIcon.CHEV_U else ElchiIcon.CHEV_D, c.muted, size = 18.dp)
        }
        if (open) {
            Column(Modifier.fillMaxWidth().clip(shape).background(c.card).border(1.dp, c.line, shape)) {
                options.forEachIndexed { i, (option, text) ->
                    if (i > 0) Spacer(Modifier.fillMaxWidth().height(1.dp).background(c.field))
                    val selected = option == value
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp)
                            .background(if (selected) c.highlight else Color.Transparent)
                            .selectable(selected, role = Role.RadioButton) {
                                onSelect(option)
                                open = false
                            }
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Text(text, Modifier.weight(1f), style = Elchi.type.secondary, color = c.text)
                        if (selected) ElchiIconView(ElchiIcon.CHECK, c.accentText, size = 18.dp)
                    }
                }
            }
        }
        if (hint != null) Text(hint, style = Elchi.type.caption, color = c.muted)
    }
}

// -- Stage 05 blocks (the prototype's skel) -----------------------------------------------------------------------

/** The prototype's `skel`: a card of grey bars while a list loads (announced as [label] to TalkBack). */
@Composable
fun SkeletonCard(label: String, modifier: Modifier = Modifier, lines: Int = 3) {
    val c = Elchi.colors
    val bar = if (c.isDark) c.field else Color(0xFFE9EDF2)
    ElchiCard(modifier.semantics { contentDescription = label }, padding = PaddingValues(horizontal = 16.dp, vertical = 16.dp)) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.fillMaxWidth(0.55f).height(14.dp).clip(CircleShape).background(bar))
            repeat(lines - 1) { i -> Box(Modifier.fillMaxWidth(if (i % 2 == 0) 0.9f else 0.7f).height(10.dp).clip(CircleShape).background(bar)) }
        }
    }
}
