package uz.elchi.app.feature.driver

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.LedgerLineDTO
import uz.elchi.app.api.generated.LedgerReferenceDTO
import uz.elchi.app.api.generated.TopupCreate
import uz.elchi.app.api.generated.TopupStatus
import uz.elchi.app.ui.theme.Tone
import java.time.Instant
import java.time.LocalDate

class WalletRulesTest {
    private fun line(kind: String, direction: String, minor: Long, at: String) =
        LedgerLineDTO(minor, 0, direction, kind, at, LedgerReferenceDTO("x", "topup_request"), "ltx_$at$kind")

    private val lines = listOf(
        line("topup", "credit", 20_000_000, "2026-09-25T10:00:00Z"),
        line("commission_capture", "debit", 1_800_000, "2026-09-30T10:00:00Z"),
        line("commission_capture", "debit", 600_000, "2026-09-30T19:30:00Z"), // 00:30 on 1 Oct in Tashkent
        line("reversal", "credit", 480_000, "2026-09-29T10:00:00Z"),
        line("adjustment", "credit", 100, "2026-09-28T10:00:00Z"),
        line("commission_capture", "debit", 900_000, "2026-09-20T10:00:00Z"), // outside the 7 days
    )

    @Test
    fun `tiles sum only what the ledger recorded in each direction`() {
        val tiles = WalletRules.tiles(lines)
        assertEquals(3_300_000L, tiles.capturedMinor)
        assertEquals(480_000L, tiles.reversedMinor)
        assertEquals(20_000_000L, tiles.topupsMinor)
        assertEquals(WalletTiles(0, 0, 0), WalletRules.tiles(emptyList()))
    }

    @Test
    fun `the chart is the last 7 Tashkent days of captured commission`() {
        val chart = WalletRules.chart(lines, Instant.parse("2026-10-01T06:00:00Z"))
        assertEquals(7, chart.size)
        assertEquals(LocalDate.parse("2026-09-25"), chart.first().day)
        assertEquals(LocalDate.parse("2026-10-01"), chart.last().day)
        assertEquals(1_800_000L, chart.first { it.day == LocalDate.parse("2026-09-30") }.minor)
        assertEquals(600_000L, chart.last().minor) // the late-evening capture belongs to the Tashkent day after
        assertEquals(2_400_000L, chart.sumOf { it.minor })
        assertFalse(WalletRules.chartEmpty(chart))
        assertTrue(WalletRules.chartEmpty(WalletRules.chart(lines.filter { it.kind != "commission_capture" }, Instant.parse("2026-10-01T06:00:00Z"))))
    }

    @Test
    fun `the top-up body sends whole so'm in minor units, trimmed optional fields, never a receipt`() {
        val body = WalletRules.topupBody("100000", "bank_transfer", "  Jasur T.  ", "")!!
        assertEquals(TopupCreate(amountMinor = 10_000_000, method = "bank_transfer", payerReference = "Jasur T.", note = null), body)
        assertNull(body.evidenceFileId)
        val json = ElchiJson.encodeToString(TopupCreate.serializer(), body)
        assertFalse(json.contains("note"))
        assertFalse(json.contains("evidence"))
        assertEquals("cash_desk", WalletRules.topupBody("5", "cash_desk", "", " kassa ")!!.method)
        assertNull(WalletRules.topupBody("0", "bank_transfer", "", ""))
        assertNull(WalletRules.topupBody("", "bank_transfer", "", ""))
        assertNull(WalletRules.topupBody("100", "card", "", ""))
        assertEquals(128, WalletRules.topupBody("1", "bank_transfer", "x".repeat(300), "")!!.payerReference!!.length)
    }

    @Test
    fun `top-up statuses read from the dictionary with their tone`() {
        assertEquals("status.pending", WalletRules.topupStatusKey(TopupStatus.PENDING))
        assertEquals("status.awaiting_second_approval", WalletRules.topupStatusKey(TopupStatus.AWAITING_SECOND_APPROVAL))
        assertEquals("status.approved", WalletRules.topupStatusKey(TopupStatus.APPROVED))
        assertEquals("status.rejected", WalletRules.topupStatusKey(TopupStatus.REJECTED))
        assertEquals(Tone.WARN, WalletRules.topupTone(TopupStatus.AWAITING_SECOND_APPROVAL))
        assertEquals(Tone.OK, WalletRules.topupTone(TopupStatus.APPROVED))
        assertEquals(Tone.ERR, WalletRules.topupTone(TopupStatus.REJECTED))
        assertEquals("+", WalletRules.signed(lines[0]))
        assertEquals("−", WalletRules.signed(lines[1]))
    }
}
