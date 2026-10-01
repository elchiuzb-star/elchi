package uz.elchi.app.api

import kotlinx.serialization.KSerializer
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder

/**
 * Enum (de)serializer that maps a value this app version does not know to [unknown] instead of failing: an
 * installed app lives for months while the server keeps adding statuses and codes.
 */
class LenientEnumSerializer<E : Enum<E>>(
    name: String,
    private val entries: List<E>,
    private val unknown: E,
    private val value: (E) -> String,
) : KSerializer<E> {
    override val descriptor = PrimitiveSerialDescriptor("uz.elchi.app.$name", PrimitiveKind.STRING)

    override fun deserialize(decoder: Decoder): E {
        val raw = decoder.decodeString()
        return entries.firstOrNull { it != unknown && value(it) == raw } ?: unknown
    }

    override fun serialize(encoder: Encoder, value: E) {
        require(value != unknown) { "${descriptor.serialName}.UNKNOWN is never sent to the server" }
        encoder.encodeString(value(value))
    }
}
