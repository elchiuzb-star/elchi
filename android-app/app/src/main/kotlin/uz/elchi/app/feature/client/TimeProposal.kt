package uz.elchi.app.feature.client

import androidx.compose.runtime.Composable
import uz.elchi.app.R
import uz.elchi.app.api.generated.ProposalVersionDTO
import uz.elchi.app.i18n.t
import java.time.format.DateTimeFormatter

/** The `{time}`, `{start}`, `{end}` of `offer.timeProposal`. */
data class TimeProposalParts(val time: String, val start: String, val end: String)

/**
 * ADR-0027 (Q153): a driver may offer to pick up outside the client's requested time. The version says so
 * (`outside_request_window`); the client then reads "Haydovchi 22:30 da olishni taklif qilmoqda (siz 18:00 - 20:00
 * so'ragansiz)". Accepting, or countering the price, is the consent - nothing else changes on the card.
 */
object TimeProposalRules {
    private val DAY_CLOCK = DateTimeFormatter.ofPattern("dd.MM, HH:mm")
    private val CLOCK = DateTimeFormatter.ofPattern("HH:mm")

    private fun format(iso: String?, pattern: DateTimeFormatter): String? =
        OrderRules.parseInstant(iso)?.atZone(ParcelRules.TASHKENT)?.format(pattern)

    /** Null unless [version] is a time proposal; the client's window ([windowStart], [windowEnd]) as "-" when unknown. */
    fun parts(version: ProposalVersionDTO?, windowStart: String?, windowEnd: String?): TimeProposalParts? {
        if (version?.outsideRequestWindow != true) return null
        val time = format(version.pickupWindowStart, DAY_CLOCK) ?: return null
        return TimeProposalParts(time, format(windowStart, DAY_CLOCK) ?: "-", format(windowEnd, CLOCK) ?: "-")
    }
}

/** The sentence, or null when the version is not a time proposal. */
@Composable
internal fun timeProposalText(version: ProposalVersionDTO?, window: Pair<String?, String?>?): String? =
    TimeProposalRules.parts(version, window?.first, window?.second)?.let { p ->
        t(R.string.offer_timeProposal, "time" to p.time, "start" to p.start, "end" to p.end)
    }
