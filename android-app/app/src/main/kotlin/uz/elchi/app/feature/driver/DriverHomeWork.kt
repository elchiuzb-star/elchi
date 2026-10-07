package uz.elchi.app.feature.driver

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.feature.client.Load
import uz.elchi.app.i18n.t
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi

/**
 * Under the home listings (Safar v3 1.11-1.14): three tiles counted on the client from the lists the tabs already read
 * (no stats endpoint), "Yangi safar rejalashtirish" - which now adds a direction (Q150: the system plans the trips) -
 * and the "offers hold nothing" line (§9 "Taklif berdim ≠ bron", kept although the design dropped it).
 */
@Composable
internal fun DriverHomeWork(work: DriverWork, nav: DriverNav, onMatches: () -> Unit) {
    val trips by work.trips.state.collectAsStateWithLifecycle()
    val proposals by work.proposals.state.collectAsStateWithLifecycle()
    val bookings by work.bookings.state.collectAsStateWithLifecycle()
    val bookingStatuses: Load<List<String>> = when (val b = bookings.bookings) {
        Load.Loading -> Load.Loading
        is Load.Failed -> Load.Failed(b.error)
        is Load.Ready -> Load.Ready(b.value.map { it.serviceStatus })
    }
    val stats = Design07Rules.homeStats(trips.trips, proposals.lists[ProposalTab.OPEN], bookingStatuses)
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        // Safarlar → "Yo'nalishlarim" (Moslar segment 2, where the trips are); Takliflar → Moslar (as on iOS).
        StatTile(t(R.string.driver_dash_statTrips), stats.trips, Modifier.weight(1f), nav.onRoutes)
        StatTile(t(R.string.client_listing_stepOffers), stats.offers, Modifier.weight(1f), onMatches)
        StatTile(t(R.string.client_orders_bookings), stats.bookings, Modifier.weight(1f), nav.onOrders)
    }
    ElchiButton(t(R.string.driver_dash_planTrip), nav.onAddDirection, Modifier.fillMaxWidth(), ButtonVariant.SOFT, icon = ElchiIcon.PLUS)
    // §9 "Taklif berdim ≠ bron": the commission is held at accept, never at proposal.
    Text(t(R.string.driver_dash_balanceNoHold), style = Elchi.type.caption, color = Elchi.colors.muted)
}

/** One tile: the label over the count ("—" while it cannot be counted); a tap opens its place. */
@Composable
private fun StatTile(label: String, value: Int?, modifier: Modifier, onClick: () -> Unit) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(18.dp)
    val shown = value?.toString() ?: "—"
    Column(
        modifier
            .shadow(10.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(shape)
            .background(c.card)
            .clickable(role = Role.Button, onClick = onClick)
            .semantics { contentDescription = "$label: $shown" }
            .heightIn(min = 64.dp)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(label, style = Elchi.type.caption, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(shown, style = Elchi.type.title.copy(fontSize = 20.sp, lineHeight = 24.sp, fontWeight = FontWeight.SemiBold), color = c.text)
    }
}
