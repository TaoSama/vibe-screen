import Foundation
import XCTest
@testable import Telemachus

final class SessionAuthorityClientTests: XCTestCase {
    override func tearDown() {
        AuthorityURLProtocol.handler = nil
        AuthorityURLProtocol.responseHeaders = [:]
        super.tearDown()
    }

    func testDefaultTransportIsEphemeralCookielessAndUsesSystemTrust() {
        let configuration = HTTPSessionAuthorityClient.makeDefaultConfiguration()

        XCTAssertNil(configuration.httpCookieStorage)
        XCTAssertFalse(configuration.httpShouldSetCookies)
        XCTAssertNil(configuration.urlCache)
        XCTAssertEqual(configuration.requestCachePolicy, .reloadIgnoringLocalAndRemoteCacheData)
        XCTAssertEqual(configuration.tlsMinimumSupportedProtocolVersion, .TLSv12)
        XCTAssertEqual(HTTPSessionAuthorityClient().tlsPolicy, .systemTrust)
    }

    func testRedirectDelegateRefusesRedirectRequestBeforeItCanBeSent() throws {
        let session = URLSession(configuration: .ephemeral)
        let original = try XCTUnwrap(URL(string: "https://signal.example.test/original"))
        let redirected = try XCTUnwrap(URL(string: "https://other.example.test/redirected"))
        let task = session.dataTask(with: original)
        let response = try XCTUnwrap(HTTPURLResponse(
            url: original,
            statusCode: 307,
            httpVersion: "HTTP/1.1",
            headerFields: ["Location": redirected.absoluteString]
        ))
        var allowedRequest: URLRequest?
        var callbackInvoked = false

        var redirectRequest = URLRequest(url: redirected)
        redirectRequest.setValue("Bearer must-not-leak", forHTTPHeaderField: "Authorization")
        SessionAuthorityRequestDelegate().urlSession(
            session,
            task: task,
            willPerformHTTPRedirection: response,
            newRequest: redirectRequest
        ) { request in
            callbackInvoked = true
            allowedRequest = request
        }

        XCTAssertTrue(callbackInvoked)
        XCTAssertNil(allowedRequest)
    }

    func testRefreshUsesOldHostCredentialAndReturnsOnlyFreshAuthorityMaterial() async throws {
        let expires = ISO8601DateFormatter().string(from: Date().addingTimeInterval(300))
        AuthorityURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/base/v1/sessions/old-session/refresh")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer old-host-token")
            XCTAssertEqual(try request.bodyData(), Data("{}".utf8))
            return (201, Data("""
            {"session_id":"new-session","role_token":"new-host-token","session_epoch":8,
             "expires_at":"\(expires)","turn":{"username":"new-user","password":"new-password",
             "ttl_seconds":300,"realm":"relay.example.test","uris":["turns:relay.example.test:5349"]}}
            """.utf8))
        }

        let replacement = try await client().refresh(current())

        XCTAssertEqual(replacement.sessionID, "new-session")
        XCTAssertEqual(replacement.sessionEpoch, 8)
        XCTAssertEqual(replacement.signaling.bearerToken, "new-host-token")
        XCTAssertEqual(replacement.signaling.role, .offerer)
        XCTAssertEqual(replacement.turn?.username, "new-user")
        XCTAssertEqual(replacement.turn?.uris.map(\.absoluteString), ["turns:relay.example.test:5349"])
    }

    func testRefreshRejectsOldSessionTokenAndEpoch() async {
        let cases = [
            "{\"session_id\":\"old-session\",\"role_token\":\"new\",\"session_epoch\":8,\"expires_at\":\"2099-01-01T00:00:00Z\"}",
            "{\"session_id\":\"new\",\"role_token\":\"old-host-token\",\"session_epoch\":8,\"expires_at\":\"2099-01-01T00:00:00Z\"}",
            "{\"session_id\":\"new\",\"role_token\":\"new\",\"session_epoch\":7,\"expires_at\":\"2099-01-01T00:00:00Z\"}",
        ]
        for body in cases {
            AuthorityURLProtocol.handler = { _ in (200, Data(body.utf8)) }
            await assertNonRetryableFailure { try await self.client().refresh(self.current()) }
        }
    }

    func testRefreshRejectsUnknownFieldsAndCredentialBearingTURNURI() async {
        let bodies = [
            "{\"session_id\":\"new\",\"role_token\":\"new\",\"session_epoch\":8,\"expires_at\":\"2099-01-01T00:00:00Z\",\"device_token\":\"secret\"}",
            "{\"session_id\":\"new\",\"role_token\":\"new\",\"session_epoch\":8,\"expires_at\":\"2099-01-01T00:00:00Z\",\"turn\":{\"username\":\"u\",\"password\":\"p\",\"ttl_seconds\":30,\"realm\":\"r\",\"uris\":[\"turn:u:p@relay.test\"]}}",
        ]
        for body in bodies {
            AuthorityURLProtocol.handler = { _ in (200, Data(body.utf8)) }
            await assertNonRetryableFailure { try await self.client().refresh(self.current()) }
        }
    }

    func testRejectsInvalidDeclaredContentLengthBeforeDecodingBody() async {
        for contentLength in ["65537", "-1", "invalid"] {
            AuthorityURLProtocol.responseHeaders = ["Content-Length": contentLength]
            AuthorityURLProtocol.handler = { _ in
                (200, Data("{\"status\":\"revoked\"}".utf8))
            }

            await assertNonRetryableFailure {
                try await self.client().revoke(
                    self.current(),
                    deviceID: "device-1",
                    signedTombstone: Data("{\"sequence\":7}".utf8)
                )
            }
        }
    }

    func testStreamingReadRejectsUndeclaredBodyAboveLimit() async {
        AuthorityURLProtocol.handler = { _ in
            (200, Data(repeating: 0x20, count: (64 * 1024) + 1))
        }

        await assertNonRetryableFailure {
            try await self.client().revoke(
                self.current(),
                deviceID: "device-1",
                signedTombstone: Data("{\"sequence\":7}".utf8)
            )
        }
    }

    func testRejectsNonHTTPSNonLoopbackEndpointBeforeNetwork() async {
        let unsafe = SessionAuthorityCredential(
            endpoint: URL(string: "http://signal.example.test")!,
            sessionID: "old-session",
            hostRoleToken: "old-host-token",
            sessionEpoch: 7
        )
        await assertNonRetryableFailure { try await self.client().refresh(unsafe) }
    }

    func testRevokeSendsScopedDeviceAndTombstoneWithoutLeakingIntoURL() async throws {
        AuthorityURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/base/v1/sessions/old-session/revoke")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer old-host-token")
            let root = try XCTUnwrap(
                JSONSerialization.jsonObject(with: try request.bodyData()) as? [String: Any]
            )
            XCTAssertEqual(root["device_id"] as? String, "device-1")
            XCTAssertEqual((root["tombstone"] as? [String: Any])?["sequence"] as? Int, 7)
            XCTAssertFalse(request.url?.absoluteString.contains("device-1") ?? true)
            return (200, Data("{\"status\":\"revoked\"}".utf8))
        }

        try await client().revoke(
            current(),
            deviceID: "device-1",
            signedTombstone: Data("{\"sequence\":7}".utf8)
        )
    }

    func testRevokeClassifiesRelayFailureAsRetryableAndDenialsAsTerminal() async {
        AuthorityURLProtocol.handler = { _ in (502, Data()) }
        do {
            try await client().revoke(
                current(),
                deviceID: "device-1",
                signedTombstone: Data("{\"sequence\":7}".utf8)
            )
            XCTFail("Expected retryable relay propagation failure")
        } catch let error as SessionAuthorityClientError {
            XCTAssertTrue(error.isRetryable)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }

        AuthorityURLProtocol.handler = { _ in (403, Data()) }
        await assertNonRetryableFailure {
            try await self.client().revoke(
                self.current(),
                deviceID: "device-1",
                signedTombstone: Data("{\"sequence\":7}".utf8)
            )
        }
    }

    private func current() -> SessionAuthorityCredential {
        SessionAuthorityCredential(
            endpoint: URL(string: "https://signal.example.test/base")!,
            sessionID: "old-session",
            hostRoleToken: "old-host-token",
            sessionEpoch: 7
        )
    }

    private func client() -> HTTPSessionAuthorityClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AuthorityURLProtocol.self]
        return HTTPSessionAuthorityClient(session: URLSession(configuration: configuration))
    }

    private func assertNonRetryableFailure<T>(
        _ operation: () async throws -> T,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        do {
            _ = try await operation()
            XCTFail("Expected failure", file: file, line: line)
        } catch let error as SessionAuthorityClientError {
            XCTAssertFalse(error.isRetryable, file: file, line: line)
        } catch {
            XCTFail("Unexpected error: \(error)", file: file, line: line)
        }
    }
}

private extension URLRequest {
    func bodyData() throws -> Data {
        if let httpBody { return httpBody }
        guard let httpBodyStream else { return Data() }
        httpBodyStream.open()
        defer { httpBodyStream.close() }
        var result = Data()
        var buffer = [UInt8](repeating: 0, count: 4_096)
        while httpBodyStream.hasBytesAvailable {
            let count = httpBodyStream.read(&buffer, maxLength: buffer.count)
            guard count >= 0 else {
                throw SessionAuthorityClientError.invalidRequest("Could not read request body stream.")
            }
            if count == 0 { break }
            result.append(contentsOf: buffer.prefix(count))
        }
        return result
    }
}

private final class AuthorityURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, Data))?
    static var responseHeaders: [String: String] = [:]

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let handler = try XCTUnwrap(Self.handler)
            let (status, data) = try handler(request)
            var headers = Self.responseHeaders
            headers["Content-Type"] = "application/json"
            let response = try XCTUnwrap(HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: status,
                httpVersion: "HTTP/1.1",
                headerFields: headers
            ))
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
