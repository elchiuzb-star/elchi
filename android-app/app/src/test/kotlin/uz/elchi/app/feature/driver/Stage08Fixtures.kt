package uz.elchi.app.feature.driver

import uz.elchi.app.api.generated.ActorSide
import uz.elchi.app.api.generated.Currency
import uz.elchi.app.api.generated.DistrictRefDTO
import uz.elchi.app.api.generated.FeedItemDTO
import uz.elchi.app.api.generated.FeedMatchDTO
import uz.elchi.app.api.generated.FeedReputationDTO
import uz.elchi.app.api.generated.ListingKind
import uz.elchi.app.api.generated.ListingOfferDTO
import uz.elchi.app.api.generated.ListingPublicDTO
import uz.elchi.app.api.generated.ListingStatus
import uz.elchi.app.api.generated.MatchGroup
import uz.elchi.app.api.generated.MatchReason
import uz.elchi.app.api.generated.MatchType
import uz.elchi.app.api.generated.PointEndDTO
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.PriceRevisionsLeftDTO
import uz.elchi.app.api.generated.ProposalDemandDTO
import uz.elchi.app.api.generated.ProposalPartyDTO
import uz.elchi.app.api.generated.ProposalStatus
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.ProposalVersionDTO
import uz.elchi.app.api.generated.ReputationLabel
import uz.elchi.app.api.generated.RouteVersionDTO
import uz.elchi.app.api.generated.RouteVersionStopDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.StopRefDTO
import uz.elchi.app.api.generated.TripDTO
import uz.elchi.app.api.generated.TripStatus
import uz.elchi.app.api.generated.TripStopDTO
import uz.elchi.app.api.generated.TripVehicleDTO
import uz.elchi.app.api.generated.VehicleDTO

/** Small builders for the Stage 08 DTOs (only the fields the rules read vary). */
object S08 {
    fun stop(id: String, name: String = id) = StopRefDTO(id = id, nameUz = name)

    fun trip(
        id: String = "trp_1",
        status: TripStatus = TripStatus.PLANNED,
        start: String = "2026-10-02T04:00:00Z",
        end: String = "2026-10-02T12:30:00Z",
        cutoff: String = start,
        stops: List<Pair<String, String>> = listOf("stp_tash" to "2026-10-02T04:00:00Z", "stp_sam" to "2026-10-02T09:28:00Z"),
        version: Long = 3,
    ) = TripDTO(
        baggageCapacityMl = 0,
        bookingCutoffAt = cutoff,
        cargoCapacityVolumeMl = 100_000,
        cargoCapacityWeightG = 20_000,
        createdAt = "2026-10-01T06:00:00Z",
        detourUsedM = 0,
        detourUsedMinutes = 0,
        detourUsedS = 0,
        id = id,
        listings = emptyList(),
        maxDetourM = 5_000,
        maxDetourMinutes = 15,
        pickupWaitMinutes = 10,
        plannedEndAt = end,
        plannedStartAt = start,
        routeVersionId = "rtv_1",
        seatCapacity = 3,
        status = status,
        stops = stops.mapIndexed { i, (stopId, at) -> TripStopDTO(dwellMinutes = 5, plannedArrivalAt = at, seq = i + 1L, stop = stop(stopId, stopId.removePrefix("stp_"))) },
        timezone = "Asia/Tashkent",
        vehicle = TripVehicleDTO(color = "oq", id = "veh_1", makeModel = "Cobalt", plateMasked = "01****KA", seatCapacity = 4),
        version = version,
    )

    fun vehicle(status: String = "approved", seats: Long = 4, kg: Long? = 80_000, ml: Long? = 400_000, id: String = "veh_1") = VehicleDTO(
        cargoMaxVolumeMl = ml,
        cargoMaxWeightG = kg,
        color = "oq",
        createdAt = "2026-09-23T10:55:02Z",
        documentFileIds = emptyList(),
        id = id,
        makeModel = "Chevrolet Cobalt",
        plateMasked = "90****AA",
        plateNumber = "90D001AA",
        seatCapacity = seats,
        verificationStatus = status,
        version = 2,
    )

    fun route(id: String = "rtv_1", durationS: Long = 30_748, stops: List<Pair<String, Long>> = listOf("stp_tash" to 0L, "stp_sam" to 19_693L, "stp_qarshi" to 30_748L)) = RouteVersionDTO(
        attribution = "",
        distanceM = 512_463,
        durationS = durationS,
        geometryPolyline = "",
        id = id,
        isEstimate = false,
        provider = "fixture",
        providerVersion = "1",
        status = "confirmed",
        // The server numbers route stops from 0; the trip body renumbers them from 1.
        stops = stops.mapIndexed { i, (stopId, cumulative) -> RouteVersionStopDTO(cumulativeDistanceM = 0, cumulativeDurationS = cumulative, seq = i.toLong(), stopId = stopId) },
    )

    fun listing(
        id: String = "lst_1",
        originStop: StopRefDTO? = null,
        destinationStop: StopRefDTO? = null,
        windowStart: String = "2026-10-02T04:00:00Z",
        windowEnd: String = "2026-10-02T13:00:00Z",
        unitMinor: Long = 12_000_000,
        quantity: Long = 1,
        basis: PriceBasis = PriceBasis.TOTAL,
        service: ServiceType = ServiceType.PARCEL,
    ) = ListingPublicDTO(
        currency = Currency.UZS,
        departureWindowEnd = windowEnd,
        departureWindowStart = windowStart,
        destinationPoint = if (destinationStop == null) PointEndDTO(address = "Samarqand, Amir Temur 18", district = DistrictRefDTO("dst_sam", "Samarqand"), lat = 39.65, lng = 66.96) else null,
        destinationStop = destinationStop,
        id = id,
        kind = ListingKind.REQUEST,
        originPoint = if (originStop == null) PointEndDTO(address = "Toshkent, Amir Temur 2", district = DistrictRefDTO("dst_tash", "Toshkent shahri"), lat = 41.31, lng = 69.28) else null,
        originStop = originStop,
        priceBasis = basis,
        quantity = quantity,
        serviceType = service,
        status = ListingStatus.PUBLISHED,
        timezone = "Asia/Tashkent",
        totalMinor = if (basis == PriceBasis.PER_SEAT) unitMinor * quantity else unitMinor,
        unitPriceMinor = unitMinor,
    )

    fun feedItem(id: String, group: MatchGroup = MatchGroup.PRIMARY, reasons: List<MatchReason> = emptyList(), type: MatchType = MatchType.ON_ROUTE) = FeedItemDTO(
        group = group,
        labels = emptyList(),
        listing = listing(id = id),
        match = FeedMatchDTO(matchType = type, reasons = reasons),
        readyToAccept = true,
        reputation = FeedReputationDTO(completedBookings = 0, label = ReputationLabel.NEW_VERIFIED, ratingCount = 0),
    )

    fun offer(label: String, total: Long, mine: Boolean = false) = ListingOfferDTO(
        currency = Currency.UZS,
        isMine = mine,
        label = label,
        pickupWindowEnd = "2026-10-02T06:00:00Z",
        pickupWindowStart = "2026-10-02T05:00:00Z",
        priceBasis = PriceBasis.TOTAL,
        quantity = 1,
        revision = 1,
        seatCapacity = 4,
        totalMinor = total,
        unitPriceMinor = total,
        updatedAt = "2026-10-01T06:00:00Z",
        vehicleClass = "car",
    )

    fun version(
        id: String = "prv_1",
        author: ActorSide = ActorSide.DRIVER,
        revision: Long = 1,
        status: ProposalStatus = ProposalStatus.ACTIVE,
        expires: String = "2026-10-01T12:00:00Z",
        total: Long = 11_000_000,
        driverLeft: Long = 2,
    ) = ProposalVersionDTO(
        authorSide = author,
        createdAt = "2026-10-01T06:00:00Z",
        currency = Currency.UZS,
        demand = ProposalDemandDTO(baggageMl = 0, cargoVolumeMl = 12_000, cargoWeightG = 5_000),
        expiresAt = expires,
        id = id,
        pickupPoint = PointEndDTO(address = "Toshkent, Amir Temur 2", district = DistrictRefDTO("dst_tash", "Toshkent shahri"), lat = 41.31, lng = 69.28),
        dropoffPoint = PointEndDTO(address = "Samarqand, Amir Temur 18", district = DistrictRefDTO("dst_sam", "Samarqand"), lat = 39.65, lng = 66.96),
        pickupWindowEnd = "2026-10-02T06:00:00Z",
        pickupWindowStart = "2026-10-02T05:00:00Z",
        priceBasis = PriceBasis.TOTAL,
        priceRevisionsLeft = PriceRevisionsLeftDTO(client = 2, driver = driverLeft),
        quantity = 1,
        revision = revision,
        status = status,
        totalMinor = total,
        unitPriceMinor = total,
    )

    fun thread(current: ProposalVersionDTO?, state: String = "open", bookingId: String? = null, versions: List<ProposalVersionDTO>? = null) = ProposalThreadDTO(
        bookingId = bookingId,
        client = ProposalPartyDTO(label = "Mijoz", side = ActorSide.CLIENT),
        currentVersion = current,
        driver = ProposalPartyDTO(label = "Haydovchi #2", side = ActorSide.DRIVER),
        id = "prt_1",
        listingId = "lst_1",
        state = state,
        versions = versions,
    )
}
