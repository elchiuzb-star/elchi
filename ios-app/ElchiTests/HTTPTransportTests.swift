import Foundation
import os
import Testing
@testable import Elchi

/// Answers requests from a per-test script and records what was sent.
final class StubProtocol: URLProtocol, @unchecked Sendable {
    typealias Handler = @Sendable (URLRequest) -> (Int, String)?
    static let handler = OSAllocatedUnfairLock<Handler?>(initialState: nil)
    static let recorded = OSAllocatedUnfairLock<[URLRequest]>(initialState: [])

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.recorded.withLock { $0.append(request) }
        guard let (status, body) = Self.handler.withLock({ $0 })?(request) else {
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
            return
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class FakeSessions: SessionStorage, @unchecked Sendable {
    private let state: OSAllocatedUnfairLock<Session?>
    init(_ session: Session?) { state = OSAllocatedUnfairLock(initialState: session) }
    func current() -> Session? { state.withLock { $0 } }
    func save(_ session: Session) { state.withLock { $0 = session } }
    func clear() { state.withLock { $0 = nil } }
}

@Suite(.serialized)
struct HTTPTransportTests {
    let sessions = FakeSessions(Session(
        accessToken: "old-access", refreshToken: "old-refresh",
        user: AuthUser(id: 1, phone: "+998901112233", fullName: nil, role: "driver", status: "active")))
    let transport: HTTPTransport

    init() {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubProtocol.self]
        transport = HTTPTransport(v1BaseURL: URL(string: "http://stub.local/api/v1")!, sessions: sessions,
                                  urlSession: URLSession(configuration: configuration))
        StubProtocol.recorded.withLock { $0 = [] }
    }

    func respond(_ handler: @escaping StubProtocol.Handler) {
        StubProtocol.handler.withLock { $0 = handler }
    }

    @Test func unwrapsEnvelopeKeepsWarningsAndMapsUnknownEnums() async throws {
        respond { _ in (200, """
            {"success":true,"data":{"id":"usr_1","phone":"+998901112233","full_name":null,"primary_role":"driver",
            "roles":["driver","courier_from_the_future"],"status":"active","created_at":"2026-09-28T08:00:00Z","new_field":1},
            "warnings":[{"code":"CONTACT_MASKED","message":"masked"}]}
            """) }

        let result = try await ElchiAPI(transport: transport).getMe()

        #expect(result.data.roles == [.driver, .unknown("courier_from_the_future")])
        #expect(result.warnings.first?.code == "CONTACT_MASKED")
        let request = try #require(StubProtocol.recorded.withLock { $0.first })
        #expect(request.url?.path == "/api/v2/me")
        #expect(request.value(forHTTPHeaderField: "Authorization") == "Bearer old-access")
        #expect(request.value(forHTTPHeaderField: "X-Elchi-Client-Features") == "promo_cash_v1")
    }

    @Test func discriminatedUnionPicksMemberByTag() throws {
        let json = """
            {"view":"driver","base_commission_minor":1,"cash_to_collect_minor":2,"commission_charged_minor":3,
            "currency":"UZS","driver_credit_minor":4,"driver_keeps_minor":5,"fare_minor":6,
            "passenger_discount_covered_minor":7,"passenger_discount_minor":8}
            """
        let promo = try JSONDecoder().decode(BookingPromo.self, from: Data(json.utf8))
        guard case .driver(let driver) = promo else { Issue.record("expected the driver view"); return }
        #expect(driver.driverKeepsMinor == 5)
    }

    @Test func errorEnvelopeBecomesAPIErrorWithServerCode() async {
        respond { _ in (409, #"{"success":false,"error":{"code":"DRIVER_NOT_ELIGIBLE","message":"no"}}"#) }
        do {
            _ = try await ElchiAPI(transport: transport).getMe()
            Issue.record("expected APIError")
        } catch let error as APIError {
            #expect(error.status == 409)
            #expect(error.code == "DRIVER_NOT_ELIGIBLE")
        } catch {
            Issue.record("unexpected \(error)")
        }
    }

    @Test func parallel401sShareOneRefresh() async throws {
        respond { request in
            if request.url?.path == "/api/v1/auth/refresh" {
                return (200, """
                    {"success":true,"data":{"access_token":"new-access","refresh_token":"new-refresh","token_type":"bearer",
                    "user":{"id":1,"phone":"+998901112233","role":"driver","status":"active"}}}
                    """)
            }
            if request.value(forHTTPHeaderField: "Authorization") == "Bearer new-access" {
                return (200, #"{"success":true,"data":"ok"}"#)
            }
            return (401, #"{"success":false,"error":{"code":"UNAUTHORIZED","message":"expired"}}"#)
        }

        async let first = transport.send(method: "GET", path: "/ping", query: [], body: Optional<JSONValue>.none, idempotencyKey: nil, as: String.self)
        async let second = transport.send(method: "GET", path: "/ping", query: [], body: Optional<JSONValue>.none, idempotencyKey: nil, as: String.self)
        let results = try await [first.data, second.data]

        #expect(results == ["ok", "ok"])
        let refreshes = StubProtocol.recorded.withLock { $0.filter { $0.url?.path == "/api/v1/auth/refresh" }.count }
        #expect(refreshes == 1)
        #expect(sessions.current()?.refreshToken == "new-refresh")
    }

    @Test func rejectedRefreshSignsOut() async {
        respond { request in
            request.url?.path == "/api/v1/auth/refresh"
                ? (401, #"{"success":false,"error":{"code":"INVALID_REFRESH_TOKEN","message":"revoked"}}"#)
                : (401, #"{"success":false,"error":{"code":"UNAUTHORIZED","message":"expired"}}"#)
        }
        _ = try? await transport.send(method: "GET", path: "/ping", query: [], body: Optional<JSONValue>.none, idempotencyKey: nil, as: String.self)
        #expect(sessions.current() == nil)
    }

    @Test func rejectedRefreshTellsTheAppOnceButAServerErrorKeepsTheSession() async {
        let ended = OSAllocatedUnfairLock(initialState: [String]())
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubProtocol.self]
        let watched = HTTPTransport(v1BaseURL: URL(string: "http://stub.local/api/v1")!, sessions: sessions,
                                    urlSession: URLSession(configuration: configuration),
                                    onSessionEnded: { session in ended.withLock { $0.append(session.user.phone) } })
        respond { request in
            request.url?.path == "/api/v1/auth/refresh"
                ? (503, #"{"success":false,"error":{"code":"SERVICE_UNAVAILABLE","message":"down"}}"#)
                : (401, #"{"success":false,"error":{"code":"UNAUTHORIZED","message":"expired"}}"#)
        }
        _ = try? await watched.send(method: "GET", path: "/ping", query: [], body: Optional<JSONValue>.none, idempotencyKey: nil, as: String.self)
        #expect(sessions.current() != nil)
        #expect(ended.withLock { $0 }.isEmpty)

        respond { request in
            request.url?.path == "/api/v1/auth/refresh"
                ? (401, #"{"success":false,"error":{"code":"REFRESH_TOKEN_REVOKED","message":"revoked"}}"#)
                : (401, #"{"success":false,"error":{"code":"UNAUTHORIZED","message":"expired"}}"#)
        }
        async let first = try? watched.send(method: "GET", path: "/ping", query: [], body: Optional<JSONValue>.none, idempotencyKey: nil, as: String.self)
        async let second = try? watched.send(method: "GET", path: "/pong", query: [], body: Optional<JSONValue>.none, idempotencyKey: nil, as: String.self)
        _ = await (first, second)
        #expect(sessions.current() == nil)
        #expect(ended.withLock { $0 } == ["+998901112233"])
    }

    @Test func bareV1SuccessDecodesButItsErrorsStayEnveloped() async throws {
        respond { request in
            request.value(forHTTPHeaderField: "Authorization") == "Bearer old-access"
                ? (200, #"{"id":40,"phone":"+998930746792","full_name":"Aziza Karimova","role":"client","status":"active"}"#)
                : (401, #"{"success":false,"error":{"code":"UNAUTHORIZED","message":"no"}}"#)
        }
        let user = try await AuthAPI(transport: transport).me()
        #expect(user.fullName == "Aziza Karimova")
        #expect(StubProtocol.recorded.withLock { $0.last?.url?.path } == "/api/v1/auth/me")
    }

    @Test func noConnectionIsNetworkErrorAndKeepsSession() async {
        respond { _ in nil }
        do {
            _ = try await transport.send(method: "GET", path: "/ping", query: [], body: Optional<JSONValue>.none, idempotencyKey: nil, as: String.self)
            Issue.record("expected APIError")
        } catch let error as APIError {
            #expect(error.code == APIError.network)
        } catch {
            Issue.record("unexpected \(error)")
        }
        #expect(sessions.current()?.accessToken == "old-access")
    }

    @Test func queryUsesWireEnumValuesAndSkipsNils() async throws {
        respond { _ in (200, #"{"success":true,"data":"ok"}"#) }
        _ = try await transport.send(method: "GET", path: "/feed", query: [("side", Role.driver), ("cursor", nil), ("limit", 20)],
                                     body: Optional<JSONValue>.none, idempotencyKey: nil, as: String.self)
        let request = try #require(StubProtocol.recorded.withLock { $0.last })
        #expect(request.url?.query == "side=driver&limit=20")
    }
}
