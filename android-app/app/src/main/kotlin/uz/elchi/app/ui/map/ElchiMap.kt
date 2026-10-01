package uz.elchi.app.ui.map

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PointF
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.PixelCopy
import android.view.SurfaceView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.calculateEndPadding
import androidx.compose.foundation.layout.calculateStartPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.graphics.createBitmap
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.yandex.mapkit.Animation
import com.yandex.mapkit.MapKitFactory
import com.yandex.mapkit.ScreenPoint
import com.yandex.mapkit.ScreenRect
import com.yandex.mapkit.geometry.BoundingBox
import com.yandex.mapkit.geometry.Geometry
import com.yandex.mapkit.geometry.Point
import com.yandex.mapkit.geometry.Polyline
import com.yandex.mapkit.logo.HorizontalAlignment
import com.yandex.mapkit.logo.VerticalAlignment
import com.yandex.mapkit.logo.Alignment as LogoAlignment
import com.yandex.mapkit.logo.Padding as LogoPadding
import com.yandex.mapkit.map.CameraListener
import com.yandex.mapkit.map.CameraPosition
import com.yandex.mapkit.map.CameraUpdateReason
import com.yandex.mapkit.map.IconStyle
import com.yandex.mapkit.map.LineStyle
import com.yandex.mapkit.map.MapLoadedListener
import com.yandex.mapkit.map.MapObjectCollection
import com.yandex.mapkit.map.SizeChangedListener
import com.yandex.mapkit.mapview.MapView
import com.yandex.runtime.image.ImageProvider
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import uz.elchi.app.BuildConfig
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import java.lang.ref.WeakReference
import kotlin.coroutines.resume

/**
 * Yandex MapKit (lite) behind one switch. The key comes from `local.properties` (`elchi.mapkitKey`) through
 * BuildConfig and is never committed. No key, a native library that does not load, or a map that never finishes
 * loading (MapKit draws nothing useful with a rejected key) all end in the same calm placeholder - no screen
 * depends on the map to be usable.
 */
object MapKitSupport {
    private const val TAG = "ElchiMap"
    private var initialized = false

    /** False when no key is configured or MapKit failed to start: [ElchiMap] shows its placeholder. */
    var usable: Boolean = false
        private set

    /**
     * The last map in this process did not finish loading within [LOAD_TIMEOUT_MS] (MapKit logs "Invalid api key"
     * and draws an empty grid; the lite SDK offers no callback for that). The next map starts on the placeholder
     * instead of waiting again, and still replaces it the moment it does load. Kept in memory only: a slow start
     * (a cold emulator, a weak network) must not hide the map on the next launch.
     */
    internal var lastLoadFailed: Boolean = false

    /** Best guess before a map is on screen: configured, started, and the last one did load. */
    val likelyAvailable: Boolean get() = usable && !lastLoadFailed

    /** Application.onCreate: MapKit wants the key before anything else touches it. */
    fun setKey() {
        val key = BuildConfig.MAPKIT_KEY
        if (key.isBlank()) return
        try {
            MapKitFactory.setApiKey(key)
            usable = true
        } catch (t: Throwable) {
            Log.w(TAG, "MapKit key rejected at start", t)
        }
    }

    /**
     * Activity.onCreate. [languageTag] is the app language stored at start ("uz"/"ru"): MapKit takes its locale
     * only before [MapKitFactory.initialize] and only once per process, so a language switch reaches the map's
     * labels on the next launch.
     */
    fun initialize(context: Context, languageTag: String) {
        if (!usable || initialized) return
        try {
            MapKitFactory.setLocale(mapKitLocale(languageTag))
            MapKitFactory.initialize(context)
            initialized = true
        } catch (t: Throwable) {
            // A missing native library for this ABI (or any start failure) must not take the app down.
            Log.w(TAG, "MapKit failed to start", t)
            usable = false
        }
    }

    fun onStart() {
        if (usable && initialized) MapKitFactory.getInstance().onStart()
    }

    fun onStop() {
        if (usable && initialized) MapKitFactory.getInstance().onStop()
    }
}

/** MapKit's locale for an app language: Uzbek (Latin) or Russian labels on the tiles. */
internal fun mapKitLocale(languageTag: String): String = if (languageTag == "ru") "ru_RU" else "uz_UZ"

/**
 * A point on the map: the ends of the direction (origin = brand ring, destination = navy pin, light on the night
 * map - the route card's glyphs) and the driver's car as the server last placed it (brand dot; grey when the position is not live).
 */
data class MapMarker(val point: GeoPoint, val kind: Kind) {
    enum class Kind { ORIGIN, DESTINATION, VEHICLE, VEHICLE_STALE }
}

/** What the camera should frame. [nonce] re-applies the same focus (the "recentre" button). */
sealed interface MapFocus {
    data class At(val point: GeoPoint, val zoom: Float, val nonce: Int = 0) : MapFocus
    data class Fit(val points: List<GeoPoint>, val nonce: Int = 0) : MapFocus
}

/**
 * The app's only map. [padding] is the part of the map covered by floating UI (top bar, bottom sheet): the camera
 * frames and centres inside what is left, so a fixed centre pin drawn over that area marks the camera target.
 * [logoBottom] lifts the Yandex logo that far above the map's bottom edge (default: the bottom [padding]).
 * [onCameraIdle] fires when a person's pan or zoom comes to rest. [onAvailability] reports false when the map is
 * not usable (the caller offers search and the district centre instead).
 */
@Composable
fun ElchiMap(
    modifier: Modifier = Modifier,
    markers: List<MapMarker> = emptyList(),
    route: List<GeoPoint> = emptyList(),
    focus: MapFocus? = null,
    padding: PaddingValues = PaddingValues(0.dp),
    logoBottom: Dp? = null,
    interactive: Boolean = true,
    onCameraIdle: ((GeoPoint) -> Unit)? = null,
    onAvailability: (Boolean) -> Unit = {},
    placeholderTitle: String,
    placeholderText: String? = null,
) {
    val availability by rememberUpdatedState(onAvailability)
    if (!MapKitSupport.usable) {
        LaunchedEffect(Unit) { availability(false) }
        MapPlaceholder(placeholderTitle, placeholderText, modifier, padding)
        return
    }

    val dark = Elchi.colors.isDark
    val brand = Elchi.colors.brand.toArgb()
    // The destination takes the route card's pin colour (navy, the text colour when dark); fills and the
    // route's outline take the card surface, so nothing glows white on the night map.
    val pin = Elchi.colors.pin.toArgb()
    val surface = Elchi.colors.card.toArgb()
    val density = LocalDensity.current
    val direction = LocalLayoutDirection.current
    val hostView = LocalView.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val idle by rememberUpdatedState(onCameraIdle)

    var loaded by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf(MapKitSupport.lastLoadFailed) }
    // MapView wants the Activity context (theme, window), not the localized configuration context.
    val mapView = remember { MapView(hostView.context) }
    val objects = remember { mapView.mapWindow.map.mapObjects.addCollection() }

    val paddingPx = with(density) {
        floatArrayOf(
            padding.calculateStartPadding(direction).toPx(),
            padding.calculateTopPadding().toPx(),
            padding.calculateEndPadding(direction).toPx(),
            padding.calculateBottomPadding().toPx(),
        )
    }
    val focusRect = remember { FocusRect() }
    focusRect.padding = paddingPx

    // MapKit keeps listeners as weak references: they live as long as this composition does.
    val loadedListener = remember {
        MapLoadedListener {
            loaded = true
            failed = false
            MapKitSupport.lastLoadFailed = false
        }
    }
    val cameraListener = remember {
        CameraListener { _, position, reason, finished ->
            if (finished && reason == CameraUpdateReason.GESTURES) idle?.invoke(GeoPoint(position.target.latitude, position.target.longitude))
        }
    }
    val sizeListener = remember { SizeChangedListener { window, _, _ -> focusRect.apply(window) } }

    DisposableEffect(mapView) {
        val map = mapView.mapWindow.map
        map.setMapLoadedListener(WeakReference(loadedListener))
        map.addCameraListener(WeakReference(cameraListener))
        mapView.mapWindow.addSizeChangedListener(WeakReference(sizeListener))
        map.isRotateGesturesEnabled = false
        map.isTiltGesturesEnabled = false
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> mapView.onStart()
                Lifecycle.Event.ON_STOP -> mapView.onStop()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            mapView.onStop()
            // Each screen builds its own map; the native side (GL surface, tiles) is released with it.
            mapView.destroy()
        }
    }

    // MapKit reports "loaded" only once the labels are in too - on a cold start that can take half a minute
    // while the tiles themselves have long been drawn. A tiny copy of the map's surface every second tells the
    // two apart sooner: an empty grid (still loading, or a rejected key) has a handful of colours, drawn tiles
    // dozens. The map is unavailable only when neither signal arrives within LOAD_TIMEOUT_MS; the probe keeps
    // going (slower) after that, so a map that loads late still replaces the placeholder.
    LaunchedEffect(Unit) {
        val start = System.currentTimeMillis()
        while (!loaded) {
            val late = System.currentTimeMillis() - start >= LOAD_TIMEOUT_MS
            if (late && !failed) {
                failed = true
                MapKitSupport.lastLoadFailed = true
            }
            delay(if (late) 3_000 else 1_000)
            val pixels = surfacePixels(mapView) ?: continue
            if (looksDrawn(pixels)) {
                loaded = true
                failed = false
                MapKitSupport.lastLoadFailed = false
            }
        }
    }
    LaunchedEffect(loaded, failed) {
        if (failed) availability(false) else if (loaded) availability(true)
    }

    LaunchedEffect(dark) { mapView.mapWindow.map.isNightModeEnabled = dark }
    LaunchedEffect(interactive) {
        val map = mapView.mapWindow.map
        map.isScrollGesturesEnabled = interactive
        map.isZoomGesturesEnabled = interactive
    }
    // Yandex's terms want its logo visible: bottom-left, just above the sheet (the recentre button owns the right).
    val logoGap = with(density) { 10.dp.toPx() }
    val logoBottomPx = logoBottom?.let { with(density) { it.toPx() } } ?: (paddingPx[3] + logoGap)
    LaunchedEffect(paddingPx.toList(), logoBottomPx) {
        focusRect.apply(mapView.mapWindow)
        mapView.mapWindow.map.logo.apply {
            setAlignment(LogoAlignment(HorizontalAlignment.LEFT, VerticalAlignment.BOTTOM))
            setPadding(LogoPadding(maxOf(paddingPx[0], logoGap).toInt(), logoBottomPx.toInt()))
        }
    }

    LaunchedEffect(markers, route, brand, pin, surface) {
        objects.clear()
        if (route.size >= 2) {
            objects.addPolyline(Polyline(route.map { Point(it.lat, it.lng) })).apply {
                setStrokeColor(brand)
                style = LineStyle().setStrokeWidth(5f).setOutlineColor(surface).setOutlineWidth(1.5f)
            }
        }
        markers.forEach { marker -> addMarker(objects, marker, hostView.context, brand, pin, surface) }
    }

    // A fit is framed again when the floating UI changes size (the home sheet grows once the route card is in);
    // a point focus is not, so a person's pan in the point picker stays where they left it.
    val fitPadding = if (focus is MapFocus.Fit) paddingPx.toList() else null
    LaunchedEffect(focus, fitPadding) {
        val target = focus ?: return@LaunchedEffect
        // The focus rect needs the view's size; wait for the first layout.
        while (mapView.mapWindow.width() == 0) delay(16)
        focusRect.apply(mapView.mapWindow)
        val map = mapView.mapWindow.map
        val position = when (target) {
            is MapFocus.At -> CameraPosition(Point(target.point.lat, target.point.lng), target.zoom, 0f, 0f)
            is MapFocus.Fit -> {
                val box = cameraBounds(target.points) ?: return@LaunchedEffect
                if (target.points.distinct().size == 1) {
                    CameraPosition(Point(target.points[0].lat, target.points[0].lng), 12f, 0f, 0f)
                } else {
                    // Fitted into the focus rect (the map minus the floating UI), with a little room for the markers.
                    val fitted = map.cameraPosition(Geometry.fromBoundingBox(BoundingBox(Point(box.first.lat, box.first.lng), Point(box.second.lat, box.second.lng))))
                    CameraPosition(fitted.target, (fitted.zoom - 0.35f).coerceAtLeast(3f), 0f, 0f)
                }
            }
        }
        map.move(position, Animation(Animation.Type.SMOOTH, 0.4f), null)
    }

    Box(modifier) {
        AndroidView(factory = { mapView }, modifier = Modifier.fillMaxSize())
        when {
            failed -> MapPlaceholder(placeholderTitle, placeholderText, Modifier.fillMaxSize(), padding)
            // Until the first tiles are drawn MapKit shows a bare grid; a calm surface with a quiet spinner (in the
            // free area, above the sheet) reads better.
            !loaded -> Box(Modifier.fillMaxSize().background(Elchi.colors.field).padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(22.dp), color = Elchi.colors.muted, strokeWidth = 2.dp)
            }
        }
    }
}

/**
 * A few pixels of the map's GL surface (scaled down by the copy), or null while there is no surface to copy.
 * MapView.getScreenshot returns null for the SurfaceView MapKit renders into; PixelCopy reads it directly.
 */
private suspend fun surfacePixels(mapView: MapView): IntArray? {
    val surface = (0 until mapView.childCount).map(mapView::getChildAt).filterIsInstance<SurfaceView>().firstOrNull() ?: return null
    if (surface.width == 0 || surface.height == 0 || !surface.holder.surface.isValid) return null
    val bitmap = createBitmap(PROBE_WIDTH, PROBE_HEIGHT)
    val copied = suspendCancellableCoroutine { cont ->
        try {
            PixelCopy.request(surface, bitmap, { result -> cont.resume(result == PixelCopy.SUCCESS) }, Handler(Looper.getMainLooper()))
        } catch (_: IllegalArgumentException) {
            cont.resume(false) // the surface went away between the check and the copy
        }
    }
    if (!copied) return null
    return IntArray(PROBE_WIDTH * PROBE_HEIGHT).also { bitmap.getPixels(it, 0, PROBE_WIDTH, 0, 0, PROBE_WIDTH, PROBE_HEIGHT) }
}

/**
 * True when the map surface shows drawn tiles rather than MapKit's empty loading grid (background, grid lines and
 * a few markers or a route line over it). Colours are compared at 4 bits per channel so antialiasing and scaling
 * noise do not count. Measured on the emulator: empty grid 3-5, tiles half in 9-15, drawn views 22-44.
 */
internal fun looksDrawn(pixels: IntArray): Boolean =
    pixels.asSequence().map { (it shr 4) and 0x0F0F0F }.distinct().count() >= DRAWN_MIN_COLOURS

/** Keeps MapKit's focus rect (the framed, centred area) equal to the map minus the floating UI. */
private class FocusRect {
    var padding: FloatArray = FloatArray(4)

    fun apply(window: com.yandex.mapkit.map.MapWindow) {
        val w = window.width().toFloat()
        val h = window.height().toFloat()
        if (w <= 0f || h <= 0f) return
        val (left, top, right, bottom) = padding
        if (w - left - right < 50f || h - top - bottom < 50f) return
        window.focusRect = ScreenRect(ScreenPoint(left, top), ScreenPoint(w - right, h - bottom))
    }
}

private fun addMarker(objects: MapObjectCollection, marker: MapMarker, context: Context, brand: Int, pin: Int, surface: Int) {
    val scale = context.resources.displayMetrics.density
    val bitmap = when (marker.kind) {
        MapMarker.Kind.ORIGIN -> ringBitmap(scale, brand, surface)
        MapMarker.Kind.DESTINATION -> pinBitmap(scale, pin, surface)
        MapMarker.Kind.VEHICLE -> dotBitmap(scale, brand)
        MapMarker.Kind.VEHICLE_STALE -> dotBitmap(scale, android.graphics.Color.rgb(0x9A, 0xA6, 0xB5))
    }
    val anchor = if (marker.kind == MapMarker.Kind.DESTINATION) PointF(0.5f, 1f) else PointF(0.5f, 0.5f)
    objects.addPlacemark().apply {
        geometry = Point(marker.point.lat, marker.point.lng)
        setIcon(ImageProvider.fromBitmap(bitmap), IconStyle().setAnchor(anchor))
    }
}

/** Origin: a surface-coloured disc with a brand ring (the route card's origin glyph). */
private fun ringBitmap(scale: Float, brand: Int, fill: Int): Bitmap {
    val size = (22 * scale).toInt()
    return createBitmap(size, size).also { bitmap ->
        val canvas = Canvas(bitmap)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        val r = size / 2f
        paint.color = fill
        canvas.drawCircle(r, r, r, paint)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 4.5f * scale
        paint.color = brand
        canvas.drawCircle(r, r, r - paint.strokeWidth / 2 - scale, paint)
    }
}

/** The car: a filled dot with a white rim and a soft halo. */
private fun dotBitmap(scale: Float, color: Int): Bitmap {
    val size = (30 * scale).toInt()
    return createBitmap(size, size).also { bitmap ->
        val canvas = Canvas(bitmap)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        val r = size / 2f
        paint.color = color
        paint.alpha = 60
        canvas.drawCircle(r, r, r, paint)
        paint.alpha = 255
        paint.color = android.graphics.Color.WHITE
        canvas.drawCircle(r, r, r * 0.55f, paint)
        paint.color = color
        canvas.drawCircle(r, r, r * 0.4f, paint)
    }
}

/** Destination: a teardrop pin whose tip is the point, with a surface-coloured hole. */
private fun pinBitmap(scale: Float, colour: Int, hole: Int): Bitmap {
    val w = (26 * scale).toInt()
    val h = (34 * scale).toInt()
    return createBitmap(w, h).also { bitmap ->
        val canvas = Canvas(bitmap)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = colour }
        val r = w / 2f
        val path = Path().apply {
            addCircle(r, r, r, Path.Direction.CW)
            moveTo(r * 0.25f, r * 1.5f)
            lineTo(r, h.toFloat())
            lineTo(r * 1.75f, r * 1.5f)
            close()
        }
        canvas.drawPath(path, paint)
        paint.color = hole
        canvas.drawCircle(r, r, r * 0.38f, paint)
    }
}

/** No map: the field colour, a pin and one honest line. Centred in the area the floating UI leaves free. */
@Composable
fun MapPlaceholder(title: String, text: String?, modifier: Modifier = Modifier, padding: PaddingValues = PaddingValues(0.dp)) {
    val c = Elchi.colors
    Box(modifier.background(c.field).padding(padding), contentAlignment = Alignment.Center) {
        Column(
            Modifier.padding(24.dp).widthIn(max = 300.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Box(Modifier.size(56.dp).clip(CircleShape).background(c.card), contentAlignment = Alignment.Center) {
                ElchiIconView(ElchiIcon.PIN, c.muted, size = 24.dp)
            }
            Text(title, style = Elchi.type.secondary.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.Medium), color = c.text, textAlign = TextAlign.Center)
            if (text != null) Text(text, style = Elchi.type.caption, color = c.muted, textAlign = TextAlign.Center)
        }
    }
}

private const val LOAD_TIMEOUT_MS = 30_000L
private const val PROBE_WIDTH = 24
private const val PROBE_HEIGHT = 48
private const val DRAWN_MIN_COLOURS = 16
