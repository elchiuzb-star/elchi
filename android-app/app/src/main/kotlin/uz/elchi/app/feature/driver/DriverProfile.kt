package uz.elchi.app.feature.driver

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.R
import uz.elchi.app.api.DriverProfileDTO
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.ReputationDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.TripDTO
import uz.elchi.app.feature.client.BookingRules
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.LogoutConfirm
import uz.elchi.app.feature.client.ProfileRules
import uz.elchi.app.feature.client.StatTiles
import uz.elchi.app.feature.client.displayPhone
import uz.elchi.app.i18n.t
import uz.elchi.app.session.Session
import uz.elchi.app.ui.components.Badge
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.ListRowStyle
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.ToggleRow
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import java.util.Locale

/** The profile's quick actions, in the design's order (`driver-profile`), plus the wallet (Q22). */
enum class ProfileAction(val icon: ElchiIcon) {
    PROFILE(ElchiIcon.USER),
    DOCUMENTS(ElchiIcon.FILE),
    ROUTES(ElchiIcon.ROUTE),
    PROPOSALS(ElchiIcon.TAG),
    BONUS(ElchiIcon.GIFT),
    WALLET(ElchiIcon.WALLET),
    ORDERS(ElchiIcon.CLIP),
    THREADS(ElchiIcon.CHAT),
    SAFETY(ElchiIcon.BLOCK),
    HELP(ElchiIcon.HEAD),
    SETTINGS(ElchiIcon.SETTINGS),
    LOGOUT(ElchiIcon.LOGOUT),
}

/** "4,8", or null for a driver nobody rated yet (the screen says "Yangi" - never an invented score, §8.2/§9). */
object DriverProfileRules {
    val MENU: List<ProfileAction> = ProfileAction.entries

    fun ratingText(reputation: ReputationDTO?, locale: Locale): String? {
        val average = reputation?.averageRating ?: return null
        if (reputation.ratingCount <= 0) return null
        return BookingRules.formatRating(average, locale)
    }

    /** "Yo'nalish": the trips still ahead or running (planned, boarding, on the way, paused). */
    fun routesCount(trips: List<TripDTO>): Int = trips.count { TripRules.isActive(it.status) }

    /** The reports the driver sent, "50+" when there are more pages than were read. */
    fun complaintsText(count: Int, more: Boolean): String = if (more) "$count+" else count.toString()
}

/** The profile's numbers: own reputation (`GET /users/{me}/reputation?service_type=parcel`) and own reports count. */
class DriverStatsViewModel(private val api: ElchiApi) : ViewModel() {
    data class State(val reputation: Load<ReputationDTO> = Load.Loading, val complaints: Load<Pair<Int, Boolean>> = Load.Loading)

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            val reputation = async { tryCall { api.getReputation(api.getMe().data.id, ServiceType.PARCEL).data } }
            val reports = async { tryCall { api.listMyReports(limit = REPORTS) } }
            reputation.await()
                .onSuccess { r -> _state.update { it.copy(reputation = Load.Ready(r)) } }
                .onFailure { e -> _state.update { if (it.reputation is Load.Ready) it else it.copy(reputation = Load.Failed(e)) } }
            reports.await()
                .onSuccess { r -> _state.update { it.copy(complaints = Load.Ready(r.data.size to (r.meta?.nextCursor != null))) } }
                .onFailure { e -> _state.update { if (it.complaints is Load.Ready) it else it.copy(complaints = Load.Failed(e)) } }
        }
    }

    private companion object {
        const val REPORTS = 50L
    }
}

/**
 * `driver-profile`: who (initials, name, phone, the verification and availability badges), the numbers that exist
 * (rating or "Yangi", completed bookings, ratings count; status, routes, complaints), the availability switch, the
 * car, and the quick actions in the design's order.
 */
@Composable
internal fun DriverProfileBody(driver: DriverViewModel, stats: DriverStatsViewModel, trips: TripsViewModel, session: Session, nav: DriverNav) {
    val s by driver.state.collectAsStateWithLifecycle()
    val st by stats.state.collectAsStateWithLifecycle()
    val tripState by trips.state.collectAsStateWithLifecycle()
    var confirmLogout by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { stats.refresh() }
    run {
        val profile = s.loaded
        val name = profile?.fullName ?: profile?.user?.fullName ?: session.user.fullName
        Avatar(name, session.user.phone, profile)
        if (s.profile is Load.Failed && profile == null) LoadFailed(t(R.string.driverProfileForm_title), (s.profile as Load.Failed).error, driver::refresh)

        val locale = Locale.forLanguageTag(languageTag())
        val reputation = (st.reputation as? Load.Ready)?.value
        val ratingValue = when (st.reputation) {
            is Load.Ready -> DriverProfileRules.ratingText(reputation, locale) ?: t(R.string.reputation_new)
            else -> "—"
        }
        StatTiles(
            listOf(
                Triple(0, t(R.string.driverProfile_rating), ratingValue),
                Triple(1, t(R.string.driverProfile_completed), reputation?.completedBookings?.toString() ?: "—"),
                // The legacy v1 count, labelled as such (driver.profile.totalLegacy) - not v2 bookings.
                Triple(2, t(R.string.driver_profile_totalLegacy), profile?.totalOrders?.toString() ?: "—"),
            ),
        )
        profile?.let { p ->
            val status = DriverStatus.from(p.verificationStatus)
            ToggleRow(
                title = t(R.string.driverProfile_availabilityTitle),
                description = uz.elchi.app.i18n.tOrNull(DriverRules.availabilitySubtitleKey(status, p.isAvailable)).orEmpty(),
                checked = p.isAvailable,
                onChange = driver::setAvailability,
                enabled = DriverRules.availabilityEnabled(status, p.isAvailable) && !s.availabilityBusy,
            )
            ElchiCard {
                val car = listOfNotNull(p.carModel, p.carColor, p.plateNumber).filter { it.isNotBlank() }.joinToString(" / ")
                CardRow(t(R.string.driverProfile_vehicle), car.ifEmpty { t(R.string.driverProfile_noVehicle) }, first = true, muted = car.isEmpty())
            }
        }
        val routes = (tripState.trips as? Load.Ready)?.value?.let { DriverProfileRules.routesCount(it).toString() } ?: "—"
        val complaints = (st.complaints as? Load.Ready)?.value?.let { (count, more) -> DriverProfileRules.complaintsText(count, more) } ?: "—"
        StatTiles(
            listOf(
                Triple(0, t(R.string.driverProfile_status), s.status?.let { statusText(it) } ?: "—"),
                Triple(1, t(R.string.driverProfile_routes), routes),
                Triple(2, t(R.string.driver_profile_complaints), complaints),
            ),
            compact = true,
        )

        SectionTitle(t(R.string.driverProfile_quickActions))
        ListCard {
            DriverProfileRules.MENU.forEachIndexed { i, action ->
                val (title, description) = actionText(action)
                ListRow(
                    title,
                    icon = action.icon,
                    description = description,
                    first = i == 0,
                    style = if (action == ProfileAction.LOGOUT) ListRowStyle.DANGER else ListRowStyle.NORMAL,
                    onClick = {
                        when (action) {
                            ProfileAction.PROFILE -> nav.onProfileForm()
                            ProfileAction.DOCUMENTS -> nav.onDocuments()
                            ProfileAction.ROUTES -> nav.onRoutes()
                            ProfileAction.PROPOSALS -> nav.onProposals()
                            ProfileAction.BONUS -> nav.onBonus()
                            ProfileAction.WALLET -> nav.onWallet()
                            ProfileAction.ORDERS -> nav.onOrders()
                            ProfileAction.THREADS -> nav.onThreads()
                            ProfileAction.SAFETY -> nav.onSafety()
                            ProfileAction.HELP -> nav.onHelp()
                            ProfileAction.SETTINGS -> nav.onSettings()
                            ProfileAction.LOGOUT -> confirmLogout = true
                        }
                    },
                )
            }
        }
    }
    if (confirmLogout) LogoutConfirm(onConfirm = { confirmLogout = false; nav.onSignOut() }, onDismiss = { confirmLogout = false })
}

@Composable
private fun actionText(action: ProfileAction): Pair<String, String> = when (action) {
    ProfileAction.PROFILE -> t(R.string.driverProfileForm_title) to t(R.string.driver_profile_editHint)
    ProfileAction.DOCUMENTS -> t(R.string.driverProfile_action_documents) to t(R.string.driverProfile_action_documentsHint)
    ProfileAction.ROUTES -> t(R.string.driverProfile_action_routes) to t(R.string.driverProfile_action_routesHint)
    ProfileAction.PROPOSALS -> t(R.string.driverProfile_action_proposals) to t(R.string.driverProfile_action_proposalsHint)
    ProfileAction.BONUS -> t(R.string.driverProfile_action_bonus) to t(R.string.driverProfile_action_bonusHint)
    ProfileAction.WALLET -> t(R.string.income_title) to t(R.string.income_topupTitle)
    ProfileAction.ORDERS -> t(R.string.driverProfile_action_orders) to t(R.string.driverProfile_action_ordersHint)
    ProfileAction.THREADS -> t(R.string.support_myThreads) to t(R.string.support_myThreadsHint)
    ProfileAction.SAFETY -> t(R.string.safety_centerTitle) to t(R.string.safety_centerDescription)
    ProfileAction.HELP -> t(R.string.driverProfile_action_support) to t(R.string.driverProfile_action_supportHint)
    ProfileAction.SETTINGS -> t(R.string.driverProfile_action_settings) to t(R.string.driver_profile_settingsHint)
    ProfileAction.LOGOUT -> t(R.string.driverProfile_action_logout) to t(R.string.driverProfile_action_logoutHint)
}

/** Initials, name (or the phone), phone, the verification badge and the availability badge. */
@Composable
private fun Avatar(name: String?, phone: String, profile: DriverProfileDTO?) {
    val c = Elchi.colors
    ElchiCard(padding = PaddingValues(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Box(Modifier.size(64.dp).clip(CircleShape).background(c.soft), contentAlignment = Alignment.Center) {
                val initials = ProfileRules.initials(name)
                if (initials != null) Text(initials, style = Elchi.type.title.copy(fontSize = 22.sp), color = c.softText)
                else ElchiIconView(ElchiIcon.TRUCK, c.softText, size = 28.dp)
            }
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(name?.takeIf { it.isNotBlank() } ?: displayPhone(phone), style = Elchi.type.section.copy(fontSize = 18.sp, fontWeight = FontWeight.SemiBold), color = c.text)
                if (!name.isNullOrBlank()) Text(displayPhone(phone), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = c.muted)
                if (profile != null) {
                    val status = DriverStatus.from(profile.verificationStatus)
                    Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Badge(statusText(status), DriverRules.statusTone(status))
                        Badge(t(if (profile.isAvailable) R.string.driverProfile_active else R.string.driverProfile_inactive), if (profile.isAvailable) Tone.BLUE else Tone.GRAY)
                    }
                }
            }
        }
    }
}
