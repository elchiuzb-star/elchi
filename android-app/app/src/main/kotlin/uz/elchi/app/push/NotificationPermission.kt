package uz.elchi.app.push

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import kotlinx.coroutines.delay

/**
 * Asks for POST_NOTIFICATIONS (Android 13+) once per install, on the signed-in home screen - never at launch or
 * on the sign-in screens. A refusal changes nothing else: the token stays registered and the inbox keeps working.
 */
@Composable
fun AskNotificationsOnce(push: PushRegistrar) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
    val context = LocalContext.current
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    LaunchedEffect(Unit) {
        if (push.permissionAsked) return@LaunchedEffect
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
            push.permissionAsked = true
            return@LaunchedEffect
        }
        // Let home appear first, so the question comes after the person sees where they are.
        delay(ASK_DELAY_MS)
        push.permissionAsked = true
        launcher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }
}

private const val ASK_DELAY_MS = 800L
