package uz.elchi.app.api

import uz.elchi.app.api.generated.TopupCreate
import uz.elchi.app.api.generated.TopupDTO

/**
 * `POST /wallet/topups`: the generated `createMyTopup` sends no `Idempotency-Key`, which the handler demands (every
 * v2 money command carries one, ADR-0005), so the same request goes through the transport with the header. One key per request the driver means: a retry after a timeout cannot file it twice.
 */
class WalletApi(private val transport: ApiTransport) {
    suspend fun createTopup(body: TopupCreate, idempotencyKey: String): ApiResult<TopupDTO> =
        transport.send("POST", "/wallet/topups", emptyList(), transport.encode(TopupCreate.serializer(), body), idempotencyKey, TopupDTO.serializer())
}
