package uz.elchi.app.feature.client

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import androidx.exifinterface.media.ExifInterface
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.io.File
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Turns a camera or gallery image into an upload: the long edge at most [MAX_EDGE] px, EXIF rotation applied,
 * JPEG. A 12 MP photo becomes a few hundred kilobytes - the driver needs to see the parcel, not its pixels.
 * The file stays in the app cache for the preview; nothing is written to the person's gallery.
 */
class PhotoCompressor(private val context: Context) {
    class UnreadableImage : Exception("image could not be decoded")

    class Photo(val file: File, val bytes: ByteArray)

    /** Where the camera writes its full-size capture (shared through the FileProvider, `cache/photos/`). */
    fun newCaptureFile(): File = File(dir(), "capture-${System.currentTimeMillis()}.jpg")

    /** [prefix] names the cache file; only the newest file of each prefix is kept (a parcel photo, a driver document). */
    suspend fun compress(uri: Uri, prefix: String = "parcel"): Photo = withContext(Dispatchers.IO) {
        val resolver = context.contentResolver
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        // A bounds-only decode returns null by design; the size lands in [bounds].
        val opened = resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds); true } ?: false
        if (!opened || bounds.outWidth <= 0 || bounds.outHeight <= 0) throw UnreadableImage()

        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= MAX_EDGE) sample *= 2
        val decoded = resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample }) }
            ?: throw UnreadableImage()

        val rotation = resolver.openInputStream(uri)?.use { stream ->
            when (ExifInterface(stream).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
                ExifInterface.ORIENTATION_ROTATE_90 -> 90f
                ExifInterface.ORIENTATION_ROTATE_180 -> 180f
                ExifInterface.ORIENTATION_ROTATE_270 -> 270f
                else -> 0f
            }
        } ?: 0f

        val longEdge = max(decoded.width, decoded.height)
        val scale = if (longEdge > MAX_EDGE) MAX_EDGE.toFloat() / longEdge else 1f
        val matrix = Matrix().apply {
            if (scale != 1f) postScale(scale, scale)
            if (rotation != 0f) postRotate(rotation)
        }
        val output = if (matrix.isIdentity) decoded else Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)

        val bytes = ByteArrayOutputStream().use { stream ->
            output.compress(Bitmap.CompressFormat.JPEG, QUALITY, stream)
            stream.toByteArray()
        }
        if (output !== decoded) decoded.recycle()
        output.recycle()

        // Only the latest photo is kept; older previews of this flow are removed.
        dir().listFiles { f -> f.name.startsWith("$prefix-") }?.forEach { it.delete() }
        val file = File(dir(), "$prefix-${System.currentTimeMillis()}.jpg").apply { writeBytes(bytes) }
        Photo(file, bytes)
    }

    private fun dir(): File = File(context.cacheDir, "photos").apply { mkdirs() }

    companion object {
        const val MAX_EDGE = 1600
        const val QUALITY = 85

        /** Target size for a preview decode of [file]: good enough for a 180dp tall card. */
        fun previewBitmap(file: File, maxEdge: Int = 900): Bitmap? {
            if (!file.exists()) return null
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(file.absolutePath, bounds)
            val longEdge = max(bounds.outWidth, bounds.outHeight)
            if (longEdge <= 0) return null
            val sample = max(1, (longEdge.toFloat() / maxEdge).roundToInt())
            return BitmapFactory.decodeFile(file.absolutePath, BitmapFactory.Options().apply { inSampleSize = sample })
        }
    }
}
