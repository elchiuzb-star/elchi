package uz.elchi.app.api

import kotlinx.serialization.json.Json

/** One JSON configuration for every request and response. */
val ElchiJson = Json {
    ignoreUnknownKeys = true // the server may add fields; an old app must keep working
    explicitNulls = false // optional fields are omitted, not sent as null
    coerceInputValues = true
    encodeDefaults = true // `const` fields (e.g. a DTO's fixed `kind`) are part of the payload
}
