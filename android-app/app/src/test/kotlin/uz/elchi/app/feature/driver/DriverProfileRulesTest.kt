package uz.elchi.app.feature.driver

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import uz.elchi.app.api.generated.ReputationDTO
import uz.elchi.app.api.generated.ReputationLabel
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.TripStatus
import java.util.Locale

class DriverProfileRulesTest {
    private fun rep(average: Double?, count: Long, completed: Long = 0) = ReputationDTO(
        averageRating = average, completedBookings = completed, completedTrips = 0, label = ReputationLabel.entries.first(),
        ratingCount = count, serviceType = ServiceType.PARCEL, userId = "usr_1",
    )

    @Test
    fun `a rating only when people rated - never an invented score`() {
        assertEquals("4,8", DriverProfileRules.ratingText(rep(4.83, 12, 30), Locale.forLanguageTag("uz")))
        assertEquals("4,8", DriverProfileRules.ratingText(rep(4.83, 12, 30), Locale.forLanguageTag("ru")))
        assertNull(DriverProfileRules.ratingText(rep(null, 0, 3), Locale.ROOT))
        assertNull(DriverProfileRules.ratingText(rep(4.5, 0), Locale.ROOT)) // an average without ratings is not trusted
        assertNull(DriverProfileRules.ratingText(null, Locale.ROOT))
    }

    @Test
    fun `routes count the trips ahead or running, complaints say when there are more`() {
        val trips = listOf(
            S08.trip("a", TripStatus.PLANNED), S08.trip("b", TripStatus.IN_PROGRESS), S08.trip("c", TripStatus.COMPLETED),
            S08.trip("d", TripStatus.INTERRUPTED), S08.trip("e", TripStatus.CANCELLED),
        )
        assertEquals(3, DriverProfileRules.routesCount(trips))
        assertEquals("0", DriverProfileRules.complaintsText(0, more = false))
        assertEquals("50+", DriverProfileRules.complaintsText(50, more = true))
    }

    @Test
    fun `the quick actions follow the design's order, the wallet after the credit, sign-out last`() {
        assertEquals(
            listOf(
                ProfileAction.PROFILE, ProfileAction.DOCUMENTS, ProfileAction.ROUTES, ProfileAction.PROPOSALS, ProfileAction.BONUS,
                ProfileAction.WALLET, ProfileAction.ORDERS, ProfileAction.THREADS, ProfileAction.SAFETY, ProfileAction.HELP,
                ProfileAction.SETTINGS, ProfileAction.LOGOUT,
            ),
            DriverProfileRules.MENU,
        )
    }

    @Test
    fun `trip commands start and end GPS publishing`() {
        assertEquals(GpsEffect.START, TripRules.gpsEffect(TripCommand.START_BOARDING))
        assertEquals(GpsEffect.START, TripRules.gpsEffect(TripCommand.DEPART))
        assertEquals(GpsEffect.FINISH, TripRules.gpsEffect(TripCommand.COMPLETE))
        assertEquals(GpsEffect.FINISH, TripRules.gpsEffect(TripCommand.CANCEL))
        assertEquals(GpsEffect.NONE, TripRules.gpsEffect(TripCommand.INTERRUPT))
        assertEquals(GpsEffect.NONE, TripRules.gpsEffect(TripCommand.RESUME))
        val trips = listOf(
            S08.trip("p", TripStatus.PLANNED, start = "2026-10-01T04:00:00Z"),
            S08.trip("late", TripStatus.IN_PROGRESS, start = "2026-10-01T09:00:00Z"),
            S08.trip("early", TripStatus.BOARDING, start = "2026-10-01T05:00:00Z"),
            S08.trip("done", TripStatus.COMPLETED, start = "2026-10-01T01:00:00Z"),
        )
        assertEquals("early", TripRules.trackable(trips)?.id)
        assertNull(TripRules.trackable(trips.filter { it.status == TripStatus.PLANNED }))
    }
}
