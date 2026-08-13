import Foundation
import XCTest
@testable import Telemachus

final class SessionAuthorityClientTests: XCTestCase {
    override func tearDown() {
        AuthorityURLProtocol.handler = nil
        super.tearDown()
    }

    func testRefreshUsesOldHostCredentialAndReturnsOnlyFreshAuthorityMaterial() async throws {
        let expires = ISO8601DateFormatter().string(from: Date().addingTimeInterval(300))
        AuthorityURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/base/v1/sessions/old-session/refresh")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer old-host-token")
            XCTAssertEqual(request.httpBody, Data("{}".utf8))
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
                JSONSerialization.jsonObject(with: try XCTUnwrap(request.httpBody)) as? [String: Any]
            )
            XCTAssertEqual(root["device_id"] as? String, "device-1")
            XCTAssertEqual(root["tombstone"] as? String, Data("signed".utf8).base64EncodedString())
            XCTAssertFalse(request.url?.absoluteString.contains("device-1") ?? true)
            return (200, Data("{\"status\":\"revoked\"}".utf8))
        }

        try await client().revoke(
            current(),
            deviceID: "device-1",
            signedTombstone: Data("signed".utf8)
        )
    }

    func testRevokeClassifiesRelayFailureAsRetryableAndDenialsAsTerminal() async {
        AuthorityURLProtocol.handler = { _ in (502, Data()) }
        do {
            try await client().revoke(current(), deviceID: "device-1", signedTombstone: nil)
            XCTFail("Expected retryable relay propagation failure")
        } catch let error as SessionAuthorityClientError {
            XCTAssertTrue(error.isRetryable)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }

        AuthorityURLProtocol.handler = { _ in (403, Data()) }
        await assertNonRetryableFailure {
            try await self.client().revoke(self.current(), deviceID: "device-1", signedTombstone: nil)
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

private final class AuthorityURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let handler = try XCTUnwrap(Self.handler)
            let (status, data) = try handler(request)
            let response = try XCTUnwrap(HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: status,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
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
