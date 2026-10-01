import Foundation
import os
import Testing
import UIKit
@testable import Elchi

/// The parcel request model against a scripted server. Part of the serialized transport suite, because both use the
/// one shared `StubProtocol`.
extension HTTPTransportTests {
    private static let listing = """
        {"id":"lst_1","kind":"request","service_type":"parcel","status":"%@","version":%d,"corridor_id":"cor_1",
        "created_at":"2026-09-28T08:00:00Z","currency":"UZS","departure_window_start":"2026-09-29T04:00:00Z",
        "departure_window_end":"2026-09-29T13:00:00Z","expires_at":"2026-09-29T13:00:00Z","owner":{"id":"usr_1","display_name":"A"},
        "payment_method":"cash","price_basis":"total","quantity":1,"terms_version":1,"timezone":"Asia/Tashkent",
        "total_minor":12000000,"unit_price_minor":12000000}
        """

    /// Answers every call the five steps make; `publishFailures` publish calls fail first with a network error.
    private func scriptServer(publishFailures: Int) {
        let failures = OSAllocatedUnfairLock(initialState: publishFailures)
        respond { request in
            let path = request.url?.path ?? ""
            switch path {
            case "/api/v2/directions/preview":
                return (200, """
                    {"success":true,"data":{"corridor_id":"cor_1","corridor_name":"Toshkent - Samarqand","route_version_id":"rtv_1",
                    "route_polyline":"_p~iF~ps|U_ulLnnqC","distance_m":400000,"duration_s":20000,"leg_distance_m":327000,
                    "leg_duration_s":16500,"max_point_offset_m":5000,"origin":{"lat":41.28,"lng":69.2,"route_offset_m":6000},
                    "destination":{"lat":39.65,"lng":66.97,"route_offset_m":10},"districts_on_route":["Chilonzor","Samarqand"]},
                    "warnings":[{"code":"CONTACT_INFO_MASKED","message":"masked"}]}
                    """)
            case "/api/v2/feature-flags/effective":
                return (200, #"{"success":true,"data":{"corridor_id":"cor_1","flags":{"passenger_enabled":false,"parcel_enabled":true,"driver_listing_enabled":false,"tracking_enabled":false}}}"#)
            case "/api/v2/parcel-categories":
                return (200, """
                    {"success":true,"data":{"confirmed":true,"synthetic":true,"items":[{"id":"pct_s","code":"small_box","icon_key":"box_small",
                    "name_uz":"Kichik quti","max_length_cm":30,"max_width_cm":20,"max_height_cm":20,"max_weight_g":5000,"max_volume_ml":12000}]}}
                    """)
            case "/api/v2/parcel-policy":
                return (200, #"{"success":true,"data":{"approved":true,"items":[],"notice":"ok"}}"#)
            case "/api/v1/files/upload":
                return (200, #"{"success":true,"data":{"file_url":"/api/v1/files/u/1.jpg?sig=x","type":"cargo_photo","mime_type":"image/jpeg","size_bytes":10,"original_filename":"parcel.jpg"},"message":"ok"}"#)
            case "/api/v2/listings":
                return (201, #"{"success":true,"data":"# + String(format: Self.listing, "draft", 1)
                    + #","warnings":[{"code":"CONTACT_INFO_MASKED","message":"masked"}]}"#)
            case "/api/v2/listings/lst_1/publish":
                let fail = failures.withLock { remaining -> Bool in
                    guard remaining > 0 else { return false }
                    remaining -= 1
                    return true
                }
                return fail ? nil : (200, #"{"success":true,"data":"# + String(format: Self.listing, "published", 2) + "}")
            default:
                return (404, #"{"success":false,"error":{"code":"NOT_FOUND","message":"\#(path)"}}"#)
            }
        }
    }

    @MainActor
    private func completeDraft() async throws -> ParcelRequestModel {
        let api = ElchiAPI(transport: transport)
        let model = ParcelRequestModel(api: api, geo: GeoAPI(transport: transport), files: FilesAPI(transport: transport),
                                       user: AuthUser(id: 1, phone: "+998901234567", fullName: "Aziza", role: "client", status: "active"))
        let region = RequestBodyTests.region
        model.setEnd(.pickup, PlaceEnd(region: region, district: RequestBodyTests.district, point: GeoPoint(lat: 41.28, lng: 69.2), address: nil))
        model.setEnd(.dropoff, PlaceEnd(region: region, district: RequestBodyTests.sam, point: GeoPoint(lat: 39.65, lng: 66.97), address: nil))
        for _ in 0..<100 where !(model.directionReady && model.parcelOpen == true) { try await Task.sleep(for: .milliseconds(20)) }
        #expect(model.directionReady)
        #expect(model.canViewRoute)
        #expect(RouteFigures.offRouteKilometres(try #require(model.preview)) == 6)

        model.suggestWindowIfEmpty()
        model.priceDigits = "120000"
        #expect(model.routeBlockers.isEmpty)
        // The sender is the signed-in person.
        #expect(model.contacts.senderName == "Aziza" && model.contacts.senderPhone == "901234567")
        model.contacts.receiverName = "Dilnoza"
        model.contacts.receiverPhone = "915552211"
        await model.loadParcelCatalog()
        model.parcelType = .box
        model.categoryId = "pct_s"
        #expect(model.parcelReady)
        await model.setPhoto(UIGraphicsImageRenderer(size: CGSize(width: 20, height: 20)).image { _ in })
        #expect(model.photoFileId == "/api/v1/files/u/1.jpg?sig=x")
        #expect(model.draft != nil)
        return model
    }

    @Test @MainActor func publishCreatesThenPublishesAndKeepsWarnings() async throws {
        scriptServer(publishFailures: 0)
        let model = try await completeDraft()

        #expect(await model.publish())

        #expect(model.published?.listing.status == .published)
        #expect(model.published?.warnings.map(\.code) == ["CONTACT_INFO_MASKED"])
        let calls = StubProtocol.recorded.withLock { $0 }
        let create = try #require(calls.first { $0.url?.path == "/api/v2/listings" })
        let publish = try #require(calls.first { $0.url?.path == "/api/v2/listings/lst_1/publish" })
        #expect(create.value(forHTTPHeaderField: "Idempotency-Key") != nil)
        #expect(publish.value(forHTTPHeaderField: "Idempotency-Key") != nil)
        #expect(create.value(forHTTPHeaderField: "Idempotency-Key") != publish.value(forHTTPHeaderField: "Idempotency-Key"))
        // The draft is cleared for the next request; the sender stays prefilled.
        #expect(model.pickup == nil && model.photoFileId == nil && model.contacts.senderName == "Aziza")
    }

    @Test @MainActor func failedPublishRetriesTheSameDraftWithTheSameKey() async throws {
        scriptServer(publishFailures: 1)
        let model = try await completeDraft()

        #expect(await model.publish() == false)
        #expect((model.publishError as? APIError)?.code == APIError.network)
        #expect(await model.publish())

        let calls = StubProtocol.recorded.withLock { $0 }
        let creates = calls.filter { $0.url?.path == "/api/v2/listings" }
        let publishes = calls.filter { $0.url?.path == "/api/v2/listings/lst_1/publish" }
        #expect(creates.count == 1) // never a second draft
        #expect(publishes.count == 2)
        #expect(publishes[0].value(forHTTPHeaderField: "Idempotency-Key") == publishes[1].value(forHTTPHeaderField: "Idempotency-Key"))
        #expect(model.published != nil)
    }

    @Test @MainActor func routeMismatchIsAProductStateNotAnError() async throws {
        respond { request in
            request.url?.path == "/api/v2/directions/preview"
                ? (409, #"{"success":false,"error":{"code":"ROUTE_MISMATCH","message":"no route"}}"#)
                : (200, #"{"success":true,"data":{"flags":{"passenger_enabled":false,"parcel_enabled":true,"driver_listing_enabled":false,"tracking_enabled":false}}}"#)
        }
        let model = ParcelRequestModel(api: ElchiAPI(transport: transport), geo: GeoAPI(transport: transport), files: FilesAPI(transport: transport),
                                       user: AuthUser(id: 1, phone: "+998901234567", fullName: nil, role: "client", status: "active"))
        let region = RequestBodyTests.region
        model.setEnd(.pickup, PlaceEnd(region: region, district: RequestBodyTests.district, point: GeoPoint(lat: 44.6, lng: 56.2), address: nil))
        model.setEnd(.dropoff, PlaceEnd(region: region, district: RequestBodyTests.sam, point: GeoPoint(lat: 39.65, lng: 66.97), address: nil))
        for _ in 0..<100 {
            if case .mismatch = model.direction { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        guard case .mismatch = model.direction else { Issue.record("expected mismatch, got \(model.direction)"); return }
        #expect(!model.canViewRoute)
        #expect(model.routeBlockers.contains(.bothPoints))
    }
}
