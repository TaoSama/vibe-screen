#!/usr/bin/env swift

import Foundation

enum ContractError: Error, CustomStringConvertible {
    case missingFile(String)
    case missingFunction(String)
    case malformedFunction(String)
    case violation(String)

    var description: String {
        switch self {
        case .missingFile(let path): return "missing source file: \(path)"
        case .missingFunction(let name): return "missing function: \(name)"
        case .malformedFunction(let name): return "could not parse function body: \(name)"
        case .violation(let message): return message
        }
    }
}

let sourceRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath + "/baseline/MacHost/Sources")

struct SourceSnapshot { let path: String; let text: String }

func readAllSources() throws -> [SourceSnapshot] {
    guard let enumerator = FileManager.default.enumerator(at: sourceRoot, includingPropertiesForKeys: nil) else {
        throw ContractError.missingFile(sourceRoot.path)
    }

    var snapshots: [SourceSnapshot] = []
    for case let url as URL in enumerator {
        guard url.pathExtension == "swift" else { continue }
        let prefix = sourceRoot.path + "/"
        let relativePath = url.path.hasPrefix(prefix) ? String(url.path.dropFirst(prefix.count)) : url.lastPathComponent
        snapshots.append(SourceSnapshot(path: relativePath, text: try String(contentsOf: url, encoding: .utf8)))
    }
    return snapshots.sorted { $0.path < $1.path }
}

func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    guard condition() else { throw ContractError.violation(message) }
}

func functionBody(named name: String, in source: String) throws -> String {
    let bounds = try functionBodyBounds(named: name, in: source)
    return String(source[source.index(after: bounds.open)..<bounds.close])
}

func functionBodyBounds(named name: String, in source: String) throws -> (open: String.Index, close: String.Index) {
    guard let declaration = functionDeclaration(named: name, in: source) else {
        throw ContractError.missingFunction(name)
    }
    guard let openBrace = bodyOpeningBrace(after: declaration.upperBound, in: source),
          let closeBrace = bodyClosingBrace(from: openBrace, in: source) else {
        throw ContractError.malformedFunction(name)
    }
    return (openBrace, closeBrace)
}

func functionDeclaration(named name: String, in source: String) -> Range<String.Index>? {
    var searchStart = source.startIndex
    while let declaration = source.range(of: "func \(name)", range: searchStart..<source.endIndex) {
        let afterName = declaration.upperBound
        if afterName == source.endIndex || !isIdentifierContinuation(source[afterName]) {
            return declaration
        }
        searchStart = afterName
    }
    return nil
}

func bodyOpeningBrace(after start: String.Index, in source: String) -> String.Index? {
    var index = start
    var parenDepth = 0
    var bracketDepth = 0
    while index < source.endIndex {
        if let skipped = skipCommentOrString(at: index, in: source) {
            index = skipped
            continue
        }

        switch source[index] {
        case "(":
            parenDepth += 1
        case ")":
            parenDepth = max(0, parenDepth - 1)
        case "[":
            bracketDepth += 1
        case "]":
            bracketDepth = max(0, bracketDepth - 1)
        case "{" where parenDepth == 0 && bracketDepth == 0:
            return index
        default:
            break
        }
        index = source.index(after: index)
    }
    return nil
}

func bodyClosingBrace(from openBrace: String.Index, in source: String) -> String.Index? {
    var depth = 0
    var index = openBrace
    while index < source.endIndex {
        if let skipped = skipCommentOrString(at: index, in: source) {
            index = skipped
            continue
        }

        let character = source[index]
        if character == "{" {
            depth += 1
        } else if character == "}" {
            depth -= 1
            if depth == 0 {
                return index
            }
        }
        index = source.index(after: index)
    }

    return nil
}

func functionNames(containing token: String, in source: String) -> [String] {
    var names: [String] = []
    var searchStart = source.startIndex
    while let declaration = source.range(of: "func ", range: searchStart..<source.endIndex) {
        let nameStart = declaration.upperBound
        guard let nameEnd = source[nameStart...].firstIndex(where: { character in
            !isIdentifierContinuation(character)
        }) else { break }
        let name = String(source[nameStart..<nameEnd])
        if let body = try? functionBody(named: name, in: String(source[declaration.lowerBound...])),
           body.contains(token) {
            names.append(name)
        }
        searchStart = nameEnd
    }
    return names
}

func functionHits(containing token: String, in sources: [SourceSnapshot]) -> [String] {
    sources.flatMap { source in
        functionNames(containing: token, in: source.text).map { "\(source.path):\($0)" }
    }.sorted()
}

func rawOccurrenceCount(of token: String, in source: String) -> Int {
    var count = 0
    var searchStart = source.startIndex
    while let range = source.range(of: token, range: searchStart..<source.endIndex) {
        count += 1
        searchStart = range.upperBound
    }
    return count
}

func rawOccurrenceCount(of token: String, in sources: [SourceSnapshot]) -> Int {
    sources.reduce(0) { $0 + rawOccurrenceCount(of: token, in: $1.text) }
}

func sourcePaths(containing token: String, in sources: [SourceSnapshot]) -> [String] {
    sources.filter { $0.text.contains(token) }.map(\.path).sorted()
}

func sourceLineHits(containing token: String, in sources: [SourceSnapshot]) -> [String] {
    sources.flatMap { source in
        source.text.split(separator: "\n", omittingEmptySubsequences: false)
            .compactMap { line in
                let trimmedLine = String(line).trimmingCharacters(in: .whitespaces)
                return line.contains(token) ? "\(source.path):\(trimmedLine)" : nil
            }
    }.sorted()
}

func requireTokenConfined(
    _ token: String,
    to expectedHits: [String],
    in sources: [SourceSnapshot]
) throws {
    let hits = functionHits(containing: token, in: sources)
    try require(
        hits == expectedHits,
        "\(token) must be confined to \(expectedHits); found \(hits)"
    )
    let rawCount = rawOccurrenceCount(of: token, in: sources)
    try require(
        rawCount == expectedHits.count,
        "\(token) has \(rawCount) raw occurrence(s), expected \(expectedHits.count); " +
            "do not place permission APIs or privacy URLs outside explicit request functions"
    )
}

func requireLineHits(
    containing token: String,
    equal expectedHits: [String],
    in sources: [SourceSnapshot]
) throws {
    let hits = sourceLineHits(containing: token, in: sources)
    try require(
        hits == expectedHits,
        "\(token) must stay on the explicit user-action allowlist; found \(hits)"
    )
}

func skipCommentOrString(at index: String.Index, in source: String) -> String.Index? {
    if hasPrefix("//", at: index, in: source) {
        var cursor = source.index(index, offsetBy: 2)
        while cursor < source.endIndex, source[cursor] != "\n" {
            cursor = source.index(after: cursor)
        }
        return cursor
    }
    if hasPrefix("/*", at: index, in: source) {
        return skipBlockComment(at: index, in: source)
    }
    return skipStringLiteral(at: index, in: source)
}

func skipBlockComment(at index: String.Index, in source: String) -> String.Index {
    var cursor = source.index(index, offsetBy: 2)
    var depth = 1
    while cursor < source.endIndex {
        if hasPrefix("/*", at: cursor, in: source) {
            depth += 1
            cursor = source.index(cursor, offsetBy: 2)
            continue
        }
        if hasPrefix("*/", at: cursor, in: source) {
            depth -= 1
            cursor = source.index(cursor, offsetBy: 2)
            if depth == 0 { return cursor }
            continue
        }
        cursor = source.index(after: cursor)
    }
    return source.endIndex
}

func skipStringLiteral(at index: String.Index, in source: String) -> String.Index? {
    var cursor = index
    var hashCount = 0
    while cursor < source.endIndex, source[cursor] == "#" {
        hashCount += 1
        cursor = source.index(after: cursor)
    }
    guard cursor < source.endIndex, source[cursor] == "\"" else { return nil }

    if hasPrefix("\"\"\"", at: cursor, in: source) {
        let contentStart = source.index(cursor, offsetBy: 3)
        let terminator = "\"\"\"" + String(repeating: "#", count: hashCount)
        return source.range(of: terminator, range: contentStart..<source.endIndex)?.upperBound
            ?? source.endIndex
    }

    var scan = source.index(after: cursor)
    while scan < source.endIndex {
        if hashCount == 0, source[scan] == "\\" {
            scan = source.index(after: scan)
            if scan < source.endIndex {
                scan = source.index(after: scan)
            }
            continue
        }
        if source[scan] == "\"" {
            var terminatorEnd = source.index(after: scan)
            var matchedHashes = 0
            while matchedHashes < hashCount,
                  terminatorEnd < source.endIndex,
                  source[terminatorEnd] == "#" {
                matchedHashes += 1
                terminatorEnd = source.index(after: terminatorEnd)
            }
            if matchedHashes == hashCount { return terminatorEnd }
        }
        scan = source.index(after: scan)
    }
    return source.endIndex
}

func hasPrefix(_ prefix: String, at index: String.Index, in source: String) -> Bool {
    source[index...].hasPrefix(prefix)
}

func isIdentifierContinuation(_ character: Character) -> Bool {
    (character >= "a" && character <= "z") ||
        (character >= "A" && character <= "Z") ||
        (character >= "0" && character <= "9") ||
        character == "_"
}

func verifyParserFixture() throws {
    let fixture = #"""
    final class Fixture {
        func startServer(
            origin: String = "{ not the body }",
            callback: @escaping () -> Bool = {
                print("default closure { also not body }")
                return true
            },
            values: [String] = ["}"]
        ) async -> Bool {
            let ignored = "body string }"
            // Comment braces must not close the body: }
            /* Block comment with { and } braces. */
            CGRequestScreenCaptureAccess()
            return ignored.isEmpty
        }
    }
    """#

    let body = try functionBody(named: "startServer", in: fixture)
    try require(body.contains("CGRequestScreenCaptureAccess()"),
                "parser fixture missed forbidden API in real function body")
    try require(body.contains("return ignored.isEmpty"),
                "parser fixture did not reach the real function body")
    try require(functionNames(containing: "CGRequestScreenCaptureAccess", in: fixture) == ["startServer"],
                "parser fixture did not attribute forbidden API to the real function body")
}

do {
    try verifyParserFixture()

    let sources = try readAllSources()
    func sourceText(_ path: String) throws -> String {
        guard let text = sources.first(where: { $0.path == path })?.text else {
            throw ContractError.missingFile(path)
        }
        return text
    }
    let appDelegate = try sourceText("AppDelegate.swift")
    let onboarding = try sourceText("PermissionOnboardingView.swift")
    let settingsWindow = try sourceText("SettingsWindow.swift")

    try require(
        !appDelegate.contains("didRequestScreenRecordingThisSession"),
        "process-local Screen Recording prompt debounce must not return"
    )

    for token in [
        "showPostUpdatePermissionHint",
        "evaluatePostUpdatePermissionHint",
        "dismissPostUpdatePermissionHint",
        "clearPostUpdatePermissionHintIfResolved",
        "currentBinaryFingerprint",
        "lastKnownBinaryFingerprint",
        "pendingPostUpdatePermissionHintFingerprint",
        "dismissedPostUpdatePermissionHintFingerprint",
        "Permissions after update",
        "Remove Vibe Screen",
        "relaunch so macOS re-prompts"
    ] {
        let paths = sourcePaths(containing: token, in: sources)
        try require(
            paths.isEmpty,
            "post-update binary fingerprint permission hint must stay removed; found \(token) in \(paths)"
        )
    }

    let promptFreeFunctions = [
        "applicationDidFinishLaunching",
        "applicationDidBecomeActive",
        "refreshPermissionState",
        "refreshStatusIndicators",
        "refreshPermissions",
        "attemptAutomaticLaunch",
        "requestServerStart",
        "startServer",
        "handleCaptureFailure",
        "scheduleUnattendedRecoveryIfEnabled",
        "showPermissionAlert",
        "checkPermissions",
        "checkAccessibilityPermission"
    ]
    let disallowedTokens = [
        "CGRequestScreenCaptureAccess",
        "AXIsProcessTrustedWithOptions",
        "kAXTrustedCheckOptionPrompt",
        "NSWorkspace.shared.open",
        "x-apple.systempreferences:",
        "requestScreenRecordingPermission()",
        "requestAccessibilityPermission()",
        "CGRequest"
    ]

    for function in promptFreeFunctions {
        let body = try functionBody(named: function, in: appDelegate)
        for token in disallowedTokens {
            try require(
                !body.contains(token),
                "\(function) must stay preflight-only; found \(token)"
            )
        }
    }

    let permissionObservationFunctions = [
        "applicationDidFinishLaunching",
        "applicationDidBecomeActive",
        "refreshPermissionState",
        "refreshPermissions",
        "checkPermissions",
        "checkAccessibilityPermission"
    ]
    for function in permissionObservationFunctions {
        let body = try functionBody(named: function, in: appDelegate)
        try require(
            body.contains("CGPreflightScreenCaptureAccess()") ||
                body.contains("AXIsProcessTrusted()") ||
                body.contains("checkPermissions()") ||
                body.contains("refreshPermissionState()"),
            "\(function) should only observe permission state or delegate to another preflight path"
        )
    }

    let screenRequest = try functionBody(named: "requestScreenRecordingPermission", in: appDelegate)
    let accessibilityRequest = try functionBody(named: "requestAccessibilityPermission", in: appDelegate)
    for (body, token, message) in [
        (screenRequest, "CGRequestScreenCaptureAccess()",
         "explicit Screen Recording action must call CGRequestScreenCaptureAccess"),
        (screenRequest, "CGPreflightScreenCaptureAccess()",
         "explicit Screen Recording action must refresh preflight state after requesting"),
        (accessibilityRequest, "AXIsProcessTrustedWithOptions(options)",
         "explicit Accessibility action must call AXIsProcessTrustedWithOptions"),
        (accessibilityRequest, "kAXTrustedCheckOptionPrompt",
         "explicit Accessibility action must request the macOS prompt")
    ] {
        try require(body.contains(token), message)
    }

    let settingsSetup = try functionBody(named: "setupSettingsWindow", in: appDelegate)
    for (text, token, message) in [
        (settingsSetup, "settings.onRequestScreenRecordingPermission",
         "settings window must wire explicit Screen Recording action"),
        (settingsSetup, "appDelegate.requestScreenRecordingPermission()",
         "settings window Screen Recording action must reach AppDelegate request"),
        (settingsSetup, "settings.onRequestAccessibilityPermission",
         "settings window must wire explicit Accessibility action"),
        (settingsSetup, "appDelegate.requestAccessibilityPermission()",
         "settings window Accessibility action must reach AppDelegate request"),
        (onboarding, "settings.requestScreenRecordingPermission()",
         "onboarding Screen Recording button must call explicit request hook"),
        (onboarding, "settings.requestAccessibilityPermission()",
         "onboarding Accessibility button must call explicit request hook"),
        (settingsWindow, "settings.requestScreenRecordingPermission()",
         "settings Screen Recording button must call explicit request hook"),
        (settingsWindow, "settings.requestAccessibilityPermission()",
         "settings Accessibility button must call explicit request hook")
    ] {
        try require(text.contains(token), message)
    }

    let confinedTokens: [(String, [String])] = [
        ("CGRequestScreenCaptureAccess", ["AppDelegate.swift:requestScreenRecordingPermission"]),
        ("AXIsProcessTrustedWithOptions", ["AppDelegate.swift:requestAccessibilityPermission"]),
        ("kAXTrustedCheckOptionPrompt", ["AppDelegate.swift:requestAccessibilityPermission"]),
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
         ["AppDelegate.swift:requestScreenRecordingPermission"]),
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
         ["AppDelegate.swift:requestAccessibilityPermission"])
    ]
    for (token, hits) in confinedTokens {
        try requireTokenConfined(token, to: hits, in: sources)
    }

    let explicitRequestLineHits: [(String, [String])] = [
        (".requestScreenRecordingPermission()", [
            "AppDelegate.swift:appDelegate.requestScreenRecordingPermission()",
            "PermissionOnboardingView.swift:settings.requestScreenRecordingPermission()",
            "SettingsWindow.swift:settings.requestScreenRecordingPermission()"
        ]),
        (".requestAccessibilityPermission()", [
            "AppDelegate.swift:appDelegate.requestAccessibilityPermission()",
            "PermissionOnboardingView.swift:settings.requestAccessibilityPermission()",
            "SettingsWindow.swift:settings.requestAccessibilityPermission()"
        ])
    ]
    for (token, hits) in explicitRequestLineHits {
        try requireLineHits(containing: token, equal: hits, in: sources)
    }
    try require(
        functionNames(containing: "NSWorkspace.shared.open", in: appDelegate) == [
            "requestScreenRecordingPermission",
            "requestAccessibilityPermission"
        ],
        "AppDelegate System Settings opens must be confined to explicit permission request functions"
    )
    let permissionAlert = try functionBody(named: "showPermissionAlert", in: appDelegate)
    try require(
        !permissionAlert.contains("x-apple.systempreferences:"),
        "manual start permission alert must not open System Settings"
    )

    print("PASS macOS permission prompt contract")
} catch {
    fputs("FAIL macOS permission prompt contract: \(error)\n", stderr)
    exit(1)
}
