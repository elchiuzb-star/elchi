package uz.elchi.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import uz.elchi.app.ui.theme.Elchi

/**
 * The prototype's centred dialog (`ov: dialog`): title, one sentence, then the buttons - a pair side by side
 * ("Chiqish" + "Qolish") or a single full-width one ("Qayta kirish"). Strings are resolved by the caller: a dialog
 * window carries the phone's language, not the app's. [dismissible] false = only a button closes it (the
 * session-expired dialog has nothing to go back to).
 */
@Composable
fun ElchiDialog(
    title: String,
    text: String,
    confirm: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
    confirmVariant: ButtonVariant = ButtonVariant.PRIMARY,
    dismiss: String? = null,
    dismissible: Boolean = true,
    /** The two buttons one under the other at full width (design 04's block overlay: long labels never cut). */
    stacked: Boolean = false,
) {
    val c = Elchi.colors
    Dialog(onDismissRequest = { if (dismissible) onDismiss() }, properties = DialogProperties(dismissOnBackPress = dismissible, dismissOnClickOutside = dismissible)) {
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(28.dp)).background(c.card).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(title, Modifier.semantics { heading() }, style = Elchi.type.title.copy(fontSize = 19.sp, lineHeight = 23.sp), color = c.text)
                Text(text, style = Elchi.type.secondary, color = c.muted)
            }
            if (dismiss != null && stacked) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    ElchiButton(confirm, onConfirm, Modifier.fillMaxWidth().height(52.dp), confirmVariant, ButtonSize.MEDIUM)
                    ElchiButton(dismiss, onDismiss, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM)
                }
            } else if (dismiss != null) {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    ElchiButton(confirm, onConfirm, Modifier.weight(1f).height(48.dp), confirmVariant, ButtonSize.MEDIUM, horizontalPadding = 10.dp)
                    ElchiButton(dismiss, onDismiss, Modifier.weight(1f).height(48.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, horizontalPadding = 10.dp)
                }
            } else {
                ElchiButton(confirm, onConfirm, Modifier.fillMaxWidth(), confirmVariant)
            }
        }
    }
}
