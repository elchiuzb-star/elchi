package uz.elchi.app

import android.app.Application
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import uz.elchi.app.api.AccountApi
import uz.elchi.app.api.AuthApi
import uz.elchi.app.api.BookingActionsApi
import uz.elchi.app.api.DriverApi
import uz.elchi.app.api.FilesApi
import uz.elchi.app.api.GeoApi
import uz.elchi.app.api.HttpTransport
import uz.elchi.app.api.LegacyOrdersApi
import uz.elchi.app.api.OkHttpLiveSocketFactory
import uz.elchi.app.api.WalletApi
import uz.elchi.app.api.trackingSocketUrl
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.deeplink.DeepLinkCenter
import uz.elchi.app.deeplink.DeepLinkRules
import uz.elchi.app.deeplink.ReferralStore
import uz.elchi.app.feature.entry.FirstRunStore
import uz.elchi.app.gps.AndroidTrackerPlatform
import uz.elchi.app.gps.AppVisibility
import uz.elchi.app.gps.DriverTracker
import uz.elchi.app.gps.ElchiTrackerApi
import uz.elchi.app.gps.FileTrackerStorage
import uz.elchi.app.i18n.LocaleStore
import uz.elchi.app.push.PushNotifier
import uz.elchi.app.push.PushRegistrar
import uz.elchi.app.session.SessionStore
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.map.MapKitSupport
import uz.elchi.app.ui.theme.ThemeStore

/** Manual dependency wiring: one instance of each for the whole process. */
class ElchiApplication : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        MapKitSupport.setKey()
        container = AppContainer(this)
        registerActivityLifecycleCallbacks(container.visibility)
        container.pushNotifier.ensureChannel()
        container.push.start()
    }
}

class AppContainer(app: Application) {
    val sessions = SessionStore(app)
    val locale = LocaleStore(app)
    val theme = ThemeStore(app)
    val firstRun = FirstRunStore(app)
    private val http = HttpTransport.defaultClient()
    private val transport = HttpTransport(BuildConfig.API_BASE_URL, sessions, http)
    val auth = AuthApi(transport)
    val account = AccountApi(transport)
    val geo = GeoApi(transport)
    val files = FilesApi(transport)
    val legacyOrders = LegacyOrdersApi(transport)
    val driver = DriverApi(transport)
    val wallet = WalletApi(transport)
    val bookingActions = BookingActionsApi(transport)
    val api = ElchiApi(transport)
    val apiBase: String = BuildConfig.API_BASE_URL

    /** The app-level banner (Stage 06): outcomes of commands, offline, 429, warnings. */
    val banners = BannerCenter()

    /** v1 orders rated in this process: their detail stops offering "Haydovchini baholang" (v1 has no "rated" flag). */
    val legacyRated: MutableSet<Long> = mutableSetOf()

    /** Debug builds only: a v1 order to open once the client flow starts (see MainActivity). */
    val debugLegacyOrder = MutableStateFlow<Long?>(null)

    /** K8 live tracking: same HTTP client, `ws(s)://<api host>/api/v2/ws`; the token goes in the first frame. */
    val liveSockets = OkHttpLiveSocketFactory(http)
    val trackingSocketUrl: String = trackingSocketUrl(BuildConfig.API_BASE_URL)

    /** The referral code from a link, kept until it is used; and links waiting for a signed-in flow. */
    val referral = ReferralStore(app)
    val links = DeepLinkCenter(referral, DeepLinkRules.hosts(BuildConfig.LINK_HOSTS))

    /** Work that outlives a screen (push token registration). */
    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** FCM (ADR-0022): the token's registration on the server, and the notifications built from data messages. */
    val push = PushRegistrar(app, api, sessions, appScope)
    val pushNotifier = PushNotifier(app) { locale.state.value }

    /** Whether an activity of the app is started (the GPS bar's background gaps). */
    val visibility = AppVisibility()

    /**
     * The driver's GPS publisher (Stage 09, Q148): one per process, it outlives screens; its state lives on one
     * thread (a single-lane dispatcher), the outbox in the app's files.
     */
    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    val tracker = DriverTracker(
        api = ElchiTrackerApi(api),
        storage = FileTrackerStorage(app),
        platform = AndroidTrackerPlatform(app, visibility),
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Default.limitedParallelism(1)),
    )
}
