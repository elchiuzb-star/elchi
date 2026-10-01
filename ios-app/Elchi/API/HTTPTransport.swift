import Foundation

/// The one HTTP layer: v1 for auth (ADR-0006), v2 for everything else. Adds the bearer token, refreshes it once
/// on 401 (single-flight, so a rotated refresh token is never spent twice), and unwraps the `{success, data}`
/// envelope into `APIResult` or `APIError`.
public final class HTTPTransport: APITransport {
    private let v1: URL
    private let v2: URL
    private let sessions: SessionStorage
    private let urlSession: URLSession
    private let refresher = Refresher()
    /// Told when the server refuses the refresh token (the session is over), with the session it ended.
    private let onSessionEnded: @Sendable (Session) -> Void

    public init(v1BaseURL: URL, sessions: SessionStorage, urlSession: URLSession = .shared,
                onSessionEnded: @escaping @Sendable (Session) -> Void = { _ in }) {
        let text = v1BaseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        v1 = URL(string: text)!
        v2 = URL(string: text.replacingOccurrences(of: #"/api/v1$"#, with: "/api/v2", options: .regularExpression))!
        self.sessions = sessions
        self.urlSession = urlSession
        self.onSessionEnded = onSessionEnded
    }

    public func send<Body: Encodable & Sendable, T: Decodable & Sendable>(
        method: String,
        path: String,
        query: [(String, (any Sendable)?)],
        body: Body?,
        idempotencyKey: String?,
        as type: T.Type
    ) async throws -> APIResult<T> {
        try await request(base: v2, method: method, path: path, query: query, body: body, idempotencyKey: idempotencyKey, auth: true)
    }

    /// A v2 endpoint whose contract types the whole envelope (`GET /feed` -> `FeedEnvelope`, which carries
    /// `meta.degraded`): on success the body is decoded as `T` itself; errors are the usual `APIError`.
    public func sendWhole<T: Decodable & Sendable>(path: String, query: [(String, (any Sendable)?)], as type: T.Type) async throws -> T {
        let result: APIResult<T> = try await request(base: v2, method: "GET", path: path, query: query, body: Optional<JSONValue>.none,
                                                     idempotencyKey: nil, auth: true, whole: true)
        return result.data
    }

    /// A media link the API returned: signed file links come back as a path on the API host
    /// (`/api/v1/files/...?exp=&sig=`), so they are resolved against it; absolute links stay as they are.
    public func mediaURL(_ reference: String) -> URL? {
        guard let url = URL(string: reference) else { return nil }
        return url.scheme == nil ? URL(string: reference, relativeTo: v1)?.absoluteURL : url
    }

    /// `/api/v1` - the endpoints v2 does not replace: auth, geocoding (the Yandex keys stay on the server), file
    /// upload and the read-only legacy orders.
    /// `bare`: the endpoint answers success without the envelope (v1 `/auth/me` returns the user itself; its errors
    /// are still enveloped).
    func sendV1<Body: Encodable & Sendable, T: Decodable & Sendable>(
        method: String, path: String, query: [(String, (any Sendable)?)] = [], body: Body?, auth: Bool, bare: Bool = false, as type: T.Type
    ) async throws -> APIResult<T> {
        try await request(base: v1, method: method, path: path, query: query, body: body, idempotencyKey: nil, auth: auth, bare: bare)
    }

    /// `/api/v1` multipart POST (`/files/upload`), with the same bearer and refresh-once behaviour.
    func uploadV1<T: Decodable & Sendable>(path: String, form: MultipartForm, as type: T.Type) async throws -> APIResult<T> {
        try await request(base: v1, method: "POST", path: path, query: [], body: Optional<JSONValue>.none, idempotencyKey: nil,
                          auth: true, form: form)
    }

    private func request<Body: Encodable & Sendable, T: Decodable & Sendable>(
        base: URL,
        method: String,
        path: String,
        query: [(String, (any Sendable)?)],
        body: Body?,
        idempotencyKey: String?,
        auth: Bool,
        form: MultipartForm? = nil,
        bare: Bool = false,
        whole: Bool = false,
        retried: Bool = false
    ) async throws -> APIResult<T> {
        let token = auth ? sessions.current()?.accessToken : nil
        var request = URLRequest(url: url(base: base, path: path, query: query))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        // Q110: this client renders F_cash wherever a discounted booking shows money. A rendering capability, never an authority.
        request.setValue("promo_cash_v1", forHTTPHeaderField: "X-Elchi-Client-Features")
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let idempotencyKey { request.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key") }
        if let form {
            request.setValue("multipart/form-data; boundary=\(form.boundary)", forHTTPHeaderField: "Content-Type")
            request.httpBody = form.body
        } else if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        } else if method != "GET" && method != "DELETE" {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = Data("{}".utf8)
        }

        let data: Data
        let status: Int
        do {
            let (payload, response) = try await urlSession.data(for: request)
            data = payload
            status = (response as? HTTPURLResponse)?.statusCode ?? 0
        } catch {
            throw APIError(status: 0, code: APIError.network, message: error.localizedDescription, details: nil)
        }

        if status == 401, let token, !retried, await refresh(staleAccessToken: token) {
            return try await self.request(base: base, method: method, path: path, query: query, body: body,
                                          idempotencyKey: idempotencyKey, auth: auth, form: form, bare: bare, whole: whole, retried: true)
        }
        return try unwrap(status: status, data: data, bare: bare, whole: whole)
    }

    private struct Success<T: Decodable>: Decodable {
        let data: T
        let warnings: [ApiWarning]?
        let meta: PageMeta?
    }

    private struct Failure: Decodable {
        let error: ErrorBody
    }

    private struct Flag: Decodable {
        let success: Bool
    }

    private func unwrap<T: Decodable & Sendable>(status: Int, data: Data, bare: Bool = false, whole: Bool = false) throws -> APIResult<T> {
        let decoder = JSONDecoder()
        if bare, (200..<300).contains(status), (try? decoder.decode(Flag.self, from: data)) == nil {
            return APIResult(data: try decoder.decode(T.self, from: data), warnings: [], meta: nil)
        }
        guard let flag = try? decoder.decode(Flag.self, from: data) else {
            throw APIError(status: status, code: APIError.server, message: "HTTP \(status) without a JSON envelope", details: nil)
        }
        if flag.success && whole {
            return APIResult(data: try decoder.decode(T.self, from: data), warnings: [], meta: nil)
        }
        if flag.success {
            let success = try decoder.decode(Success<T>.self, from: data)
            return APIResult(data: success.data, warnings: success.warnings ?? [], meta: success.meta)
        }
        guard let failure = try? decoder.decode(Failure.self, from: data) else {
            throw APIError(status: status, code: APIError.server, message: "HTTP \(status)", details: nil)
        }
        throw APIError(status: status, code: failure.error.code, message: failure.error.message, details: failure.error.details)
    }

    /// True when a new access token is in place. Offline, a 5xx or a rate limit keep the session (nothing is known
    /// about it); a refused refresh token clears it and says so once (`SessionExpiryPolicy`).
    private func refresh(staleAccessToken: String) async -> Bool {
        await refresher.run(staleAccessToken: staleAccessToken) { [self] in
            guard let session = sessions.current() else { return false }
            if session.accessToken != staleAccessToken { return true } // another request already refreshed it
            do {
                let tokens: APIResult<TokenResponse> = try await request(
                    base: v1, method: "POST", path: "/auth/refresh", query: [],
                    body: RefreshRequest(refreshToken: session.refreshToken), idempotencyKey: nil, auth: false, retried: true)
                sessions.save(Session(accessToken: tokens.data.accessToken, refreshToken: tokens.data.refreshToken, user: tokens.data.user))
                return true
            } catch let error as APIError {
                if SessionExpiryPolicy.decision(error) == .relogin {
                    sessions.clear()
                    onSessionEnded(session)
                }
                return false
            } catch {
                return false
            }
        }
    }

    private func url(base: URL, path: String, query: [(String, (any Sendable)?)]) -> URL {
        var components = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        let items: [URLQueryItem] = query.compactMap { key, value in
            guard let value else { return nil }
            let text: String
            switch value {
            case let wire as any WireEnum: text = wire.rawValue
            case let flag as Bool: text = flag ? "true" : "false"
            default: text = "\(value)"
            }
            return text.isEmpty ? nil : URLQueryItem(name: key, value: text)
        }
        components.queryItems = items.isEmpty ? nil : items
        // URLComponents leaves "+" as is, and servers read it as a space: an offset date (`…T00:00:00+05:00`) must
        // arrive with its plus.
        components.percentEncodedQuery = components.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
        return components.url!
    }
}

/// Serializes token refreshes: callers that saw the same stale token share one refresh.
private actor Refresher {
    private var running: (token: String, task: Task<Bool, Never>)?

    func run(staleAccessToken: String, _ work: @escaping @Sendable () async -> Bool) async -> Bool {
        if let running, running.token == staleAccessToken { return await running.task.value }
        let task = Task { await work() }
        running = (staleAccessToken, task)
        let result = await task.value
        running = nil
        return result
    }
}

/// A `multipart/form-data` body: text fields and file parts, in order.
struct MultipartForm: Sendable {
    let boundary = "elchi-\(UUID().uuidString)"
    private(set) var body = Data()

    mutating func field(_ name: String, _ value: String) {
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
    }

    mutating func file(_ name: String, filename: String, mimeType: String, data: Data) {
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\nContent-Type: \(mimeType)\r\n\r\n".utf8))
        body.append(data)
        body.append(Data("\r\n".utf8))
    }

    /// The closing boundary; call once, after the last part.
    mutating func finish() {
        body.append(Data("--\(boundary)--\r\n".utf8))
    }
}
