package uz.elchi.app.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import uz.elchi.app.R
import uz.elchi.app.i18n.t
import uz.elchi.app.ui.icons.ElchiIcon

/*
 * The prototype's shared states (`states`): loading, an empty list, nothing found. One look for every screen that
 * waits on the server.
 */

/** Loading: [count] skeleton cards (3 by default, as the design and iOS), announced once as "Yuklanmoqda...". */
@Composable
fun LoadingState(modifier: Modifier = Modifier, count: Int = 3, lines: Int = 3) {
    val label = t(R.string.common_loading)
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        repeat(count) { SkeletonCard(label, lines = lines) }
    }
}

/** An empty list: the parcel icon and [title] (by default "Hozircha buyurtmalar yo'q"). */
@Composable
fun EmptyListState(modifier: Modifier = Modifier, title: String = t(R.string.orders_empty), description: String? = null, icon: ElchiIcon = ElchiIcon.PKG) {
    EmptyState(icon, title, modifier, description = description)
}

/**
 * Nothing to show for this link (404 / not yours): the search icon, "Ma'lumot topilmadi", why (DESIGN10 6.3: the link
 * is old or the data is not this person's - never "deleted", v1 orders are not) and a way back. Null = no reason line.
 */
@Composable
fun NotFoundState(onBack: () -> Unit, modifier: Modifier = Modifier, description: String? = t(R.string.client_v3archive_notFoundHint)) {
    Column(modifier.fillMaxWidth().padding(top = 24.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        EmptyState(ElchiIcon.SEARCH, t(R.string.driverProfile_notFound), description = description)
        ElchiButton(t(R.string.common_back), onBack, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM)
    }
}
