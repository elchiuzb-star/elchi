import Foundation
import Observation
import UIKit

/// A value the screen loads from the server.
enum Loadable<Value> {
    case loading
    case loaded(Value)
    case failed(Error)

    var value: Value? {
        if case .loaded(let value) = self { return value }
        return nil
    }
}

/// Where the direction check stands (Q88: the server, never the client, decides whether a route serves two places).
enum DirectionCheck {
    case idle
    case checking
    case ready(DirectionPreviewDTO)
    /// `ROUTE_MISMATCH`: a normal product state ("not on an ELCHI route yet"), said as such.
    case mismatch
    case failed(Error)
}

/// The parcel photo on step 4: shown at once, uploaded right away, `file_url` kept for the request.
enum PhotoState {
    case none
    case uploading(UIImage)
    case uploaded(UIImage, fileId: String)
    case failed(UIImage, Error)

    var image: UIImage? {
        switch self {
        case .none: nil
        case .uploading(let image), .uploaded(let image, _), .failed(let image, _): image
        }
    }
}

/// What the success screen shows: the summary card (route, window, total) and one note per server warning (e.g.
/// `CONTACT_INFO_MASKED`).
struct PublishedRequest {
    let listing: ListingDTO
    let warnings: [ApiWarning]
    var fromRegion: RegionDTO?
    var toRegion: RegionDTO?
    var windowStart: Date?
    var windowEnd: Date?
    var totalMinor: Int = 0
}

/// What the home's locate button did with "Qayerdan".
enum LocateOutcome: Equatable {
    /// "Qayerdan" now holds the current location.
    case set
    /// A place was already chosen: the map only centred.
    case kept
    /// Outside Uzbekistan or far from every district centre (or the catalogue could not be read).
    case outside
}

/// Stage 02: the client's parcel request from the home screen to "published" (same behaviour as Android's
/// ParcelRequestViewModel). One instance per signed-in client, so the draft survives moving between the steps.
@MainActor @Observable
final class ParcelRequestModel {
    private let api: ElchiAPI
    private let files: FilesAPI
    let geo: GeoAPI
    let user: AuthUser

    // Catalogue (region -> district, Q88).
    private(set) var regions: Loadable<[RegionDTO]> = .loading
    private(set) var districts: [String: Loadable<[DistrictDTO]>] = [:]

    // Direction.
    private(set) var pickup: PlaceEnd?
    private(set) var dropoff: PlaceEnd?
    private(set) var direction: DirectionCheck = .idle
    /// Effective service flags: country scope until a direction is found, then that corridor's (Q5). A failed read
    /// closes everything (Q26). Nil while unknown.
    private(set) var flags: EffectiveFlagValuesDTO?
    /// The country-scope answer, kept: whether the Taksi / Pochta segment exists at all (K7/Q89).
    private(set) var countryFlags: EffectiveFlagValuesDTO?
    /// Pochta or Taksi. Taksi only while passenger is enabled somewhere the person can see (else back to parcel).
    var mode: ServiceType = .parcel

    // Taksi: how many people (1, 2, 3 or the whole cabin = 4); nothing until the person picks.
    var seatCount: Int?

    // Step 1: route summary.
    var windowStart: Date?
    var windowEnd: Date?
    var priceDigits = ""

    // Step 2: contacts (the sender is the signed-in person; prefilled).
    var contacts = ContactsForm()

    // Step 3: parcel.
    var parcelType: ParcelType?
    var categoryId: String?
    private(set) var catalog: Loadable<ParcelCategoryCatalogDTO> = .loading
    private(set) var policy: Loadable<ParcelPolicyDTO> = .loading

    // Step 4: photo.
    private(set) var photo: PhotoState = .none

    // Step 5: publish.
    private(set) var publishing = false
    private(set) var publishError: Error?
    private(set) var published: PublishedRequest?

    /// One `Idempotency-Key` per user action, reused when the same action is retried (ADR-0005).
    private var createAttempt: (key: String, body: Data)?
    /// A draft the server already holds: a retry publishes it instead of creating a second one.
    private var createdDraft: (id: String, version: Int, body: Data, warnings: [ApiWarning])?
    private var publishAttempt: (key: String, listingId: String, version: Int)?

    private var directionTask: Task<Void, Never>?

    init(api: ElchiAPI, geo: GeoAPI, files: FilesAPI, user: AuthUser) {
        self.api = api
        self.geo = geo
        self.files = files
        self.user = user
        prefillSender()
    }

    // MARK: Catalogue

    func loadRegions() async {
        if regions.value != nil { return }
        regions = .loading
        do { regions = .loaded(try await api.listRegions().data) } catch { regions = .failed(error) }
    }

    func loadDistricts(region: RegionDTO) async {
        if districts[region.id]?.value != nil { return }
        districts[region.id] = .loading
        do {
            districts[region.id] = .loaded(try await api.listDistricts(regionId: region.id, limit: 500).data)
        } catch {
            districts[region.id] = .failed(error)
        }
    }

    func districtList(_ region: RegionDTO) -> [DistrictDTO] { districts[region.id]?.value ?? [] }

    /// Every district (the locate button's nearest-centre search), read once.
    private var allDistricts: [DistrictDTO]?
    /// The locate button: with "Qayerdan" still empty, the person's position becomes it - the nearest district centre
    /// (v2 ids) and the reverse-geocoded street - and the direction check runs as for any picked place.
    func fillPickup(from point: GeoPoint) async -> LocateOutcome {
        guard pickup == nil else { return .kept }
        if allDistricts == nil { allDistricts = try? await api.listDistricts(limit: 500).data }
        guard let district = LocateRules.district(near: point, in: allDistricts ?? []) else { return .outside }
        await loadRegions()
        let region = LocateRules.region(of: district, in: regions.value ?? [])
        let geocoded = try? await geo.reverseGeocode(point, language: language)
        let address = geocoded.flatMap { $0.isLocal ? nil : $0.formattedAddress }.flatMap { $0.isEmpty ? nil : PointPickerModel.withoutCountry($0) }
        // Chosen by hand while the lookups ran: that choice stands.
        guard pickup == nil else { return .kept }
        setEnd(.pickup, PlaceEnd(region: region, district: district, point: point, address: address, currentLocation: true))
        return .set
    }

    /// The language the geocoder answers in (the app's).
    var language: AppLocale = .uz

    // MARK: Direction

    func end(_ side: EndSide) -> PlaceEnd? { side == .pickup ? pickup : dropoff }

    /// A place was chosen; as soon as both ends are set the server is asked whether a confirmed route serves them.
    func setEnd(_ side: EndSide, _ end: PlaceEnd) {
        if side == .pickup { pickup = end } else { dropoff = end }
        checkDirection()
    }

    /// The home card's swap button: "Qayerdan" and "Qayerga" change places, and the direction is checked again.
    func swapEnds() {
        (pickup, dropoff) = (dropoff, pickup)
        checkDirection()
    }

    var preview: DirectionPreviewDTO? {
        if case .ready(let preview) = direction { return preview }
        return nil
    }

    /// The line to draw: only the leg between the two places, not the whole corridor route the preview returns.
    var routeLeg: [GeoPoint] {
        guard let preview else { return [] }
        let line = Polyline.decode(preview.routePolyline)
        guard let from = pickup?.point, let to = dropoff?.point else { return line }
        return Polyline.leg(line, from: from, to: to)
    }

    /// "Direction ready" = both places set AND the server found a route for them.
    var directionReady: Bool { preview != nil }

    /// The parcel service is open here (country scope before a direction exists, then its corridor).
    var parcelOpen: Bool? { flags.map(\.parcelEnabled) }

    /// The Taksi / Pochta segment: passenger enabled in the country or on the corridor of the chosen direction.
    var taxiVisible: Bool { PassengerGate.modeVisible(countryFlags) || PassengerGate.modeVisible(flags) }

    var canViewRoute: Bool { PassengerGate.canViewRoute(directionReady: directionReady, flags: flags, mode: mode) }

    /// The red line under "Yo'nalishni ko'rish" when the chosen service is closed here.
    var closedKey: String? { PassengerGate.closedKey(flags, mode: mode) }

    func loadCountryFlags() async {
        guard countryFlags == nil else { return }
        let read = await readFlags(corridorId: nil)
        countryFlags = read
        if preview == nil { flags = read }
        keepModeVisible()
    }

    /// One effective-flags read; a failure closes everything (Q26).
    private func readFlags(corridorId: String?) async -> EffectiveFlagValuesDTO {
        (try? await api.effectiveFlags(corridorId: corridorId).data.flags) ?? PassengerGate.closed
    }

    /// Taksi chosen where the segment is gone (passenger off everywhere the person sees): back to Pochta.
    private func keepModeVisible() {
        if mode == .passenger && !taxiVisible { mode = .parcel }
    }

    private func checkDirection() {
        directionTask?.cancel()
        guard let pickup, let dropoff else {
            direction = .idle
            return
        }
        direction = .checking
        directionTask = Task { [weak self] in
            guard let self else { return }
            do {
                let preview = try await api.previewDirection(
                    originLat: pickup.point.lat, originLng: pickup.point.lng, originDistrictId: pickup.district.id,
                    destinationLat: dropoff.point.lat, destinationLng: dropoff.point.lng, destinationDistrictId: dropoff.district.id).data
                if Task.isCancelled { return }
                direction = .ready(preview)
                // Q5: services open per corridor - re-read the flags for this one (the web client reads the country).
                let read = await readFlags(corridorId: preview.corridorId)
                if Task.isCancelled { return }
                flags = read
                keepModeVisible()
            } catch let error as APIError where error.code == "ROUTE_MISMATCH" {
                if !Task.isCancelled { direction = .mismatch }
            } catch {
                if !Task.isCancelled { direction = .failed(error) }
            }
        }
    }

    func retryDirection() { checkDirection() }

    // MARK: Step 1

    /// Offers tomorrow 09:00-18:00 (Tashkent) the first time the step opens; never overwrites a choice.
    func suggestWindowIfEmpty(now: Date = Date()) {
        var suggested = DepartureWindow.suggested(now: now)
        #if DEBUG
        // UI tests (Taksi): a window that starts in N minutes, so a trip boarding now can serve the request.
        if let minutes = Int(UserDefaults.standard.string(forKey: "uiTestWindowFromNow") ?? "") {
            let start = Date(timeIntervalSince1970: ((now.timeIntervalSince1970 / 60).rounded(.up) + Double(minutes)) * 60)
            suggested = (start, start.addingTimeInterval(5 * 3600))
        }
        #endif
        if windowStart == nil { windowStart = suggested.start }
        if windowEnd == nil { windowEnd = suggested.end }
    }

    var priceMinor: Int { Money.minor(fromSoum: priceDigits) }

    var routeBlockers: [RouteBlocker] {
        RouteBlocker.check(directionReady: directionReady, start: windowStart, end: windowEnd, priceMinor: priceMinor)
    }

    /// The taxi block on the home sheet (window, people, price per person).
    var taxiHomeBlockers: [RouteBlocker] {
        RouteBlocker.taxiHome(start: windowStart, end: windowEnd, priceMinor: priceMinor, seatCount: seatCount)
    }

    /// The contact step (people, what is sent, the photo).
    var contactBlockers: [ContactBlocker] {
        ContactBlocker.check(contacts: contacts, parcelType: parcelType, hasCategory: selectedCategory != nil, photoUploaded: photoFileId != nil)
    }

    // MARK: Step 2

    private func prefillSender() {
        contacts.senderName = user.fullName ?? ""
        contacts.senderPhone = UzPhone.localDigits(fromE164: user.phone)
    }

    // MARK: Step 3

    func loadParcelCatalog(force: Bool = false) async {
        if !force, catalog.value != nil, policy.value != nil { return }
        async let categories = api.parcelCategories()
        async let rules = api.parcelPolicy()
        do { catalog = .loaded(try await categories.data) } catch { catalog = .failed(error) }
        do { policy = .loaded(try await rules.data) } catch { policy = .failed(error) }
        // A category that is no longer offered is not a choice any more.
        if let categoryId, !(catalog.value?.items ?? []).contains(where: { $0.id == categoryId }) { self.categoryId = nil }
    }

    func retryParcelCatalog() async {
        catalog = .loading
        policy = .loading
        await loadParcelCatalog(force: true)
    }

    var selectedCategory: ParcelCategoryDTO? { catalog.value?.items?.first { $0.id == categoryId } }

    /// Q140: sizes come only from a confirmed server catalogue, and a category must be chosen.
    var parcelReady: Bool { catalog.value?.confirmed == true && selectedCategory != nil && parcelType != nil }

    // MARK: Step 4

    /// Shows the photo at once and uploads a JPEG no larger than 1600 px on the long side.
    func setPhoto(_ image: UIImage) async {
        let task = Task { await upload(image) }
        photoTask = task
        await task.value
    }

    @ObservationIgnored private var photoTask: Task<Void, Never>?

    private func upload(_ image: UIImage) async {
        photo = .uploading(image)
        let jpeg = await Task.detached(priority: .userInitiated) { PhotoCompressor.jpeg(image) }.value
        guard let jpeg else {
            photo = .failed(image, APIError(status: 0, code: "VALIDATION_ERROR", message: "", details: nil))
            return
        }
        do {
            let uploaded = try await files.uploadCargoPhoto(jpeg: jpeg)
            if Task.isCancelled { return }
            photo = .uploaded(image, fileId: uploaded.fileUrl)
        } catch {
            if Task.isCancelled { return }
            photo = .failed(image, error)
        }
    }

    /// The photo tile's delete: the request goes back to "no photo" (the uploaded file is simply not used).
    func removePhoto() {
        photoTask?.cancel()
        photo = .none
    }

    func retryPhoto() async {
        if let image = photo.image { await setPhoto(image) }
    }

    var photoFileId: String? {
        if case .uploaded(_, let fileId) = photo { return fileId }
        return nil
    }

    // MARK: Step 5

    /// Everything gathered, or nil while a step is incomplete.
    var draft: ParcelRequestDraft? {
        guard mode == .parcel, let pickup, let dropoff, directionReady, let windowStart, let windowEnd, routeBlockers.isEmpty,
              contacts.isComplete, let parcelType, let categoryId, parcelReady, let photoFileId else { return nil }
        return ParcelRequestDraft(pickup: pickup, dropoff: dropoff, windowStart: windowStart, windowEnd: windowEnd, priceMinor: priceMinor,
                                  contacts: contacts, parcelType: parcelType, categoryId: categoryId, photoFileId: photoFileId)
    }

    /// Taksi: both places, the window, the people and the price per person (no contacts, parcel or photo steps).
    var passengerDraft: PassengerRequestDraft? {
        guard mode == .passenger, let pickup, let dropoff, directionReady, let windowStart, let windowEnd, routeBlockers.isEmpty,
              let seatCount else { return nil }
        return PassengerRequestDraft(pickup: pickup, dropoff: dropoff, windowStart: windowStart, windowEnd: windowEnd, seats: seatCount,
                                     unitPriceMinor: priceMinor)
    }

    /// The body for the chosen service, or nil while a step is incomplete.
    var listingCreate: ListingCreate? {
        mode == .passenger ? passengerDraft?.listingCreate() : draft?.listingCreate()
    }

    /// Taksi: what the people pay together (`n × per person`).
    var passengerTotalMinor: Int { PassengerMoney.total(seats: seatCount ?? 1, unitMinor: priceMinor) }

    /// What the request costs in all: the people's total for Taksi, the price for Pochta.
    var totalMinor: Int { mode == .passenger ? passengerTotalMinor : priceMinor }

    /// Create the draft, then publish it. If the draft was created but publishing failed, a retry publishes that
    /// same draft (never a second one) unless the person changed something in between.
    func publish() async -> Bool {
        guard let request = listingCreate, !publishing else { return false }
        let body = Self.fingerprint(request)
        publishing = true
        publishError = nil
        defer { publishing = false }
        do {
            let created: (id: String, version: Int, body: Data, warnings: [ApiWarning])
            if let existing = createdDraft, existing.body == body {
                created = existing
            } else {
                let key = createAttempt?.body == body ? createAttempt!.key : UUID().uuidString
                createAttempt = (key, body)
                let result = try await api.createListing(body: request, idempotencyKey: key)
                created = (result.data.id, result.data.version, body, result.warnings)
                createdDraft = created
            }
            let publishKey = publishAttempt.flatMap { $0.listingId == created.id && $0.version == created.version ? $0.key : nil }
                ?? UUID().uuidString
            publishAttempt = (publishKey, created.id, created.version)
            let result = try await api.publishListing(listingId: created.id, body: ListingCommand(expectedVersion: created.version),
                                                      idempotencyKey: publishKey)
            published = PublishedRequest(listing: result.data, warnings: Self.unique(created.warnings + result.warnings),
                                         fromRegion: pickup?.region, toRegion: dropoff?.region, windowStart: windowStart,
                                         windowEnd: windowEnd, totalMinor: totalMinor)
            resetDraft()
            return true
        } catch {
            publishError = error
            if let apiError = error as? APIError, apiError.code == "VERSION_CONFLICT" { await refreshDraftVersion() }
            return false
        }
    }

    /// After `VERSION_CONFLICT` the next tap publishes against the server's current version.
    private func refreshDraftVersion() async {
        guard let draft = createdDraft, let listing = try? await api.getListing(listingId: draft.id).data,
              case .number(let version)? = listing["version"] else { return }
        createdDraft?.version = Int(version)
    }

    /// Back to an empty home after a published request (the sender stays prefilled).
    func resetDraft() {
        directionTask?.cancel()
        pickup = nil
        dropoff = nil
        direction = .idle
        windowStart = nil
        windowEnd = nil
        priceDigits = ""
        seatCount = nil
        contacts = ContactsForm()
        prefillSender()
        parcelType = nil
        categoryId = nil
        photoTask?.cancel()
        photo = .none
        publishError = nil
        createAttempt = nil
        createdDraft = nil
        publishAttempt = nil
    }

    func clearPublished() { published = nil }

    private static func fingerprint(_ body: ListingCreate) -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        return (try? encoder.encode(body)) ?? Data()
    }

    private static func unique(_ warnings: [ApiWarning]) -> [ApiWarning] {
        var seen = Set<String>()
        return warnings.filter { seen.insert($0.code).inserted }
    }
}

/// Resize to at most 1600 px on the long side and encode as JPEG (the upload limit is the server's; this keeps
/// mobile data small).
enum PhotoCompressor {
    static let maxSide: CGFloat = 1600

    static func jpeg(_ image: UIImage, maxSide: CGFloat = PhotoCompressor.maxSide, quality: CGFloat = 0.8) -> Data? {
        let size = image.size
        let longest = max(size.width, size.height)
        guard longest > 0 else { return nil }
        let scale = min(1, maxSide / longest)
        let target = CGSize(width: (size.width * scale).rounded(), height: (size.height * scale).rounded())
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        let resized = UIGraphicsImageRenderer(size: target, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: target)) }
        return resized.jpegData(compressionQuality: quality)
    }
}
