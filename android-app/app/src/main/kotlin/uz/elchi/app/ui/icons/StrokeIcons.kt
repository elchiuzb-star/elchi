package uz.elchi.app.ui.icons

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.dp

/**
 * Icons the order-form design adds on top of the generated kit ([ElchiIcon]): the same 24dp, 1.9 stroke drawing,
 * built from the prototype's own path data (`K.P.swap`, `K.P.edit`). Tinted by the caller like the kit's icons.
 * Hand-written on purpose: the kit is generated for both apps from `scripts/native_icons.json`, which this change
 * does not touch.
 */
object StrokeIcons {
    /** "Almashtirish" (the route card's swap of the two ends). */
    val Swap: ImageVector by lazy { stroke("swap", "M7 4v16M3 8l4-4 4 4M17 20V4M13 16l4 4 4-4") }

    /** "Tahrirlash" (a review row's pencil). */
    val Edit: ImageVector by lazy { stroke("edit", "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z") }

    private fun stroke(name: String, path: String): ImageVector =
        ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).addPath(
            pathData = PathParser().parsePathString(path).toNodes(),
            stroke = SolidColor(Color.Black),
            strokeLineWidth = 1.9f,
            strokeLineCap = StrokeCap.Round,
            strokeLineJoin = StrokeJoin.Round,
        ).build()
}
