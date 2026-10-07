package uz.elchi.app.feature.driver

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.R
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.DirectionRequestItemDTO
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.StepScaffold
import uz.elchi.app.feature.client.categoryName
import uz.elchi.app.feature.client.soum
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.NotFoundState
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.tone
import java.time.format.DateTimeFormatter

/**
 * "E'lon tafsiloti" (Safar v3 §6): one request from the direction feed or a home card. The request is the DD5 item
 * already in memory (no extra read); the rival board is the same anonymous `GET /listings/{id}/offers` as on the
 * offer screen (Q95; closed → hidden).
 */
class DirectionListingViewModel(private val api: ElchiApi, val item: DirectionRequestItemDTO?) : ViewModel() {
    data class State(val board: Load<BoardSummary>? = Load.Loading)

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    init {
        loadBoard()
    }

    fun loadBoard() {
        val id = item?.listing?.id ?: return
        viewModelScope.launch {
            tryCall { api.listListingOffers(id, limit = 50).data }
                .onSuccess { offers -> _state.update { it.copy(board = Load.Ready(OfferRules.board(offers))) } }
                .onFailure { e -> _state.update { it.copy(board = if ((e as? ApiException)?.status == 404) null else Load.Failed(e)) } }
        }
    }
}

@Composable
fun DirectionListingScreen(
    vm: DirectionListingViewModel,
    driver: DriverViewModel,
    nav: DriverNav,
    mine: MyFeedOffer?,
    onBack: () -> Unit,
    onOffer: () -> Unit,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val ds by driver.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val item = vm.item
    val status = ds.status
    val gated = status != null && DriverRules.gate(status) != GateVariant.NONE
    val threadId = mine?.threadId ?: item?.myThreadId
    StepScaffold(
        title = t(R.string.driver_v3trip_listingTitle),
        onBack = onBack,
        footer = if (!gated && item != null) {
            {
                // Safar v3 6.7: offered → the thread (its history, Q100), else the direction offer (DD6).
                if (threadId != null) ElchiButton(t(R.string.driver_feed_viewOffer), { nav.onThread(threadId) }, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL)
                else ElchiButton(t(R.string.driverFeed_sendOffer), onOffer, Modifier.fillMaxWidth())
            }
        } else null,
    ) {
        if (gated && status != null) {
            VerificationGate(
                status, onDocuments = nav.onDocuments, onProfile = nav.onProfileForm, onSupport = nav.onHelp,
                statusWord = ds.verify?.let { tOrNull(it.labelKey) },
                profileLabel = tOrNull(DriverRules.profileButtonKey(ds.profileDone)),
            )
            return@StepScaffold
        }
        if (item == null) {
            NotFoundState(onBack)
            return@StepScaffold
        }
        val l = item.listing
        val ru = appRu()
        ElchiCard(padding = PaddingValues(16.dp)) {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.size(44.dp).clip(CircleShape).background(c.highlight), contentAlignment = Alignment.Center) { ElchiIconView(kindIcon(l), c.accentText, size = 20.dp) }
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(placeTitle(l), style = Elchi.type.bodyStrong.copy(fontSize = 17.sp, lineHeight = 21.sp), color = c.text)
                        Text(windowLine(l), style = Elchi.type.caption.copy(fontSize = 12.5.sp), color = c.muted)
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val tone = c.tone(HomeListingRules.tagTone(item))
                    Text(
                        tOrNull(HomeListingRules.tagKey(item)).orEmpty(),
                        Modifier.weight(1f, fill = false).clip(CircleShape).background(tone.bg).padding(horizontal = 12.dp, vertical = 5.dp),
                        style = Elchi.type.caption.copy(fontWeight = FontWeight.SemiBold), color = tone.fg, maxLines = 1,
                    )
                    Box(Modifier.weight(1f))
                    Column(horizontalAlignment = Alignment.End) {
                        Text(t(R.string.driver_v3trip_clientPriceLabel), style = Elchi.type.caption.copy(fontSize = 11.5.sp), color = c.muted)
                        Text(soum(l.totalMinor), style = Elchi.type.title.copy(fontSize = 22.sp, lineHeight = 27.sp, fontWeight = FontWeight.SemiBold), color = c.text, maxLines = 1)
                    }
                }
            }
        }
        // Safar v3 6.2: what this driver already offered (or the client's yes).
        val mineLine = when (mine) {
            is MyFeedOffer.Sent -> t(R.string.offerBid_yourOffer, "price" to soum(mine.totalMinor))
            is MyFeedOffer.Accepted -> t(R.string.driver_feed_clientAccepted)
            null -> if (item.myThreadId != null) t(R.string.dir_card_myOffer) else null
        }
        mineLine?.let {
            Text(
                it,
                Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(c.soft).padding(horizontal = 16.dp, vertical = 12.dp),
                style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.softText,
            )
        }
        // Safar v3 6.3: the places (an address, else the district - never a stop, Q158), the day, the window, what.
        val fallback = t(R.string.app_endLabel_mapPlace)
        val start = OrderRules.parseInstant(l.departureWindowStart)
        ElchiCard {
            CardRow(t(R.string.routeSummary_pickup), DirectionRules.place(l.originPoint, fallback), first = true)
            CardRow(t(R.string.routeSummary_dropoff), DirectionRules.place(l.destinationPoint, fallback))
            CardRow(t(R.string.publicShare_date), start?.atZone(uz.elchi.app.feature.client.ParcelRules.TASHKENT)?.format(DAY) ?: "—")
            CardRow(t(R.string.driver_v3trip_timeWindow), "${DirectionRules.clock(l.departureWindowStart)}–${DirectionRules.clock(l.departureWindowEnd)}")
            if (l.serviceType == ServiceType.PARCEL) {
                CardRow(t(R.string.tripDetail_parcel), l.parcelCategory?.let { categoryName(it, ru) } ?: "—")
            } else {
                CardRow(t(R.string.client_taxi_seats), l.quantity.toString())
            }
            // ADR-0027: when the car would be at the pickup.
            item.pickupEta?.let { CardRow(t(R.string.driverBid_pickupWindow), DirectionRules.dayClock(it), strong = item.fit == DirectionRules.TIME_DIFFERS) }
        }
        // Q6: the parcel photo is only for the assigned driver - say when it shows instead of a placeholder.
        if (l.serviceType == ServiceType.PARCEL) Text(t(R.string.driver_v3trip_photoAfterBooking), style = Elchi.type.caption, color = c.muted)
        RivalBoard(s.board, vm::loadBoard)
    }
}

private val DAY: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM.yyyy")
