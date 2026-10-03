package uz.elchi.app.feature.client

import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.ApiResult
import uz.elchi.app.api.ApiTransport
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.ProposalThreadDTO
import java.util.concurrent.CopyOnWriteArrayList

/**
 * DESIGN03 §6, the Taksi counter bug: a `per_seat` offer is countered per person end to end - the form prefills and
 * compares the seat price, "Jami" is seats x price, and `unit_price_minor` carries the seat price (never the total,
 * which the server would multiply by the seats again). A parcel (`total`) offer keeps working in whole prices.
 */
class OfferCounterTest {

    private fun version(basis: String, quantity: Long, unit: Long, revision: Long = 1, author: String = "driver", id: String = "prv_1") =
        """{"id":"$id","listing_terms_version":1,"revision":$revision,"author_side":"$author","status":"active","status_reason":null,
        "pickup_window_start":"2030-09-30T05:00:00Z","pickup_window_end":"2030-09-30T07:00:00Z","quantity":$quantity,"price_basis":"$basis",
        "unit_price_minor":$unit,"total_minor":${unit * quantity},"currency":"UZS","expires_at":"2030-09-30T11:40:00Z","created_at":"2030-09-29T09:48:00Z",
        "demand":{"baggage_ml":0,"cargo_weight_g":0,"cargo_volume_ml":0},"price_revisions_left":{"client":2,"driver":2}}"""

    private fun thread(basis: String, quantity: Long, unit: Long, versions: String = "null", current: String = version(basis, quantity, unit)): ProposalThreadDTO =
        ElchiJson.decodeFromString(
            ProposalThreadDTO.serializer(),
            """{"id":"prp_1","listing_id":"lst_1","listing_terms_version":1,"state":"open","client":{"side":"client","label":"Mijoz"},
            "driver":{"side":"driver","label":"Haydovchi #2"},"current_version":$current,"versions":$versions}""",
        )

    @Test
    fun `a per-seat offer is countered per person - prefill, same-price check and total`() {
        // 3 people x 150 000 so'm = 450 000 so'm.
        val units = OrderRules.counterUnits(thread("per_seat", 3, 15_000_000).currentVersion!!)
        assertTrue(units.perSeat)
        assertEquals(15_000_000L, units.base)
        assertEquals(Pair(null, CounterProblem.SAME), OrderRules.counterCheck("150 000", units))
        // The total is NOT "the same price": it would be 3 x 450 000 on the server.
        assertEquals(45_000_000L to null, OrderRules.counterCheck("450000", units))
        assertEquals(14_000_000L to null, OrderRules.counterCheck("140000", units))
        assertEquals(42_000_000L, units.total(14_000_000))
    }

    @Test
    fun `a parcel offer is countered as the whole price`() {
        val units = OrderRules.counterUnits(thread("total", 1, 14_000_000).currentVersion!!)
        assertFalse(units.perSeat)
        assertEquals(14_000_000L, units.base)
        assertEquals(Pair(null, CounterProblem.SAME), OrderRules.counterCheck("140000", units))
        assertEquals(13_500_000L to null, OrderRules.counterCheck("135 000", units))
        assertEquals(13_500_000L, units.total(13_500_000))
    }

    @Test
    fun `an empty or zero price is refused with its reason`() {
        val units = OrderRules.counterUnits(thread("total", 1, 14_000_000).currentVersion!!)
        assertEquals(Pair(null, CounterProblem.EMPTY), OrderRules.counterCheck("", units))
        assertEquals(Pair(null, CounterProblem.EMPTY), OrderRules.counterCheck("0", units))
    }

    @Test
    fun `the counter sends the seat price as unit_price_minor and reports the server's total`() = runBlocking {
        val sent = CopyOnWriteArrayList<Pair<String, JsonElement?>>()
        val transport = object : ApiTransport {
            override fun <T> encode(serializer: KSerializer<T>, value: T): JsonElement = ElchiJson.encodeToJsonElement(serializer, value)

            @Suppress("UNCHECKED_CAST")
            override suspend fun <T> send(method: String, path: String, query: List<Pair<String, Any?>>, body: JsonElement?, idempotencyKey: String?, result: KSerializer<T>): ApiResult<T> {
                sent += "$method $path" to body
                if (path.endsWith("/promo-preview")) throw ApiException(404, "NOT_FOUND", "no promo")
                check(method == "POST" && path == "/proposals/prp_1/counter") { "unexpected $method $path" }
                val unit = body!!.jsonObject["unit_price_minor"]!!.jsonPrimitive.long
                // The server multiplies by the seats: the reply is the client's new version.
                val answered = thread("per_seat", 3, unit, current = version("per_seat", 3, unit, revision = 2, author = "client", id = "prv_2"))
                return ApiResult(answered as T)
            }
        }
        val board = OfferBoard(this, ElchiApi(transport), termsVersion = { 1L }, reload = {})
        val offer = thread("per_seat", 3, 15_000_000)

        board.openCounter(offer)
        assertEquals("150000", board.state.value.counterDigits)
        // The driver's own seat price cannot be sent back; the tap says why instead.
        board.sendCounter(offer)
        assertEquals(CounterProblem.SAME, board.state.value.counterProblem)

        board.setCounterDigits(offer, "140 000")
        assertNull(board.state.value.counterProblem)
        board.sendCounter(offer)
        val done = withTimeout(5_000) { board.state.first { it.busyThread == null && it.notice != null } }

        val counter = sent.single { it.first == "POST /proposals/prp_1/counter" }.second!!.jsonObject
        assertEquals(14_000_000L, counter["unit_price_minor"]!!.jsonPrimitive.long)
        assertEquals(1L, counter["expected_revision"]!!.jsonPrimitive.long)
        assertEquals(OfferNotice.CounterSent(42_000_000), done.notice)
        assertNull(done.counterFor)
    }

    @Test
    fun `the client's earlier price is the newest earlier client version`() {
        val v1 = version("total", 1, 15_000_000, revision = 1, author = "driver", id = "prv_1")
        val v2 = version("total", 1, 13_500_000, revision = 2, author = "client", id = "prv_2")
        val v3 = version("total", 1, 14_200_000, revision = 3, author = "driver", id = "prv_3")
        val countered = thread("total", 1, 14_200_000, versions = "[$v1,$v2,$v3]", current = v3)
        assertTrue(OrderRules.driverCountered(countered))
        assertEquals(13_500_000L, OrderRules.clientPreviousTotal(countered))
        // A first offer is not a counter, and a list row (no versions) has no earlier price.
        assertFalse(OrderRules.driverCountered(thread("total", 1, 15_000_000)))
        assertNull(OrderRules.clientPreviousTotal(thread("total", 1, 14_200_000, current = v3)))
    }
}
