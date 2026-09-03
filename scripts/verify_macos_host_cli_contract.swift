#!/usr/bin/env swift

import Foundation

enum ContractError: Error, CustomStringConvertible {
    case missingFile(String)
    case commandFailed(String, Int32, String)
    case violation(String)

    var description: String {
        switch self {
        case .missingFile(let path): return "missing source file: \(path)"
        case .commandFailed(let command, let status, let output):
            return "command failed (\(status)): \(command)\n\(output)"
        case .violation(let message): return message
        }
    }
}

let sourceRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
let mainPath = "baseline/MacHost/Sources/main.swift"
let parserPath = "baseline/MacHost/Sources/HostCommandLine.swift"
let actionableErrorStatesPath = "docs/changes/2026-08-23-actionable-error-states/actionable-error-states.json"

let expectedCommandFlags = [
    "--issue-phase3-internet-lease",
    "--transport-self-test",
    "--reliability-self-test",
    "--protocol-v1-self-test",
    "--video-encoder-self-test",
    "--audio-capture-self-test",
    "--host-self-test",
    "--phase3-internet-self-test",
    "--phase3-internet-lease-self-test",
    "--phase3-webrtc-loopback-self-test",
    "--phase3-webrtc-signaling-self-test",
    "--phase3-product-signaling-self-test",
    "--phase3-product-android-interop-host",
    "--phase3-real-media-self-test"
]

let expectedGuiFlags = [
    "--headless-benchmark",
    "--prefer-cgdisplaystream"
]

let expectedParseFailureMessages = [
    "Unknown Vibe Screen Host CLI flag: --self-test",
    "Multiple Vibe Screen Host CLI commands are not supported.",
    "Unknown iOS loopback scenario."
]

let parseFailurePermissionPromptTokens = [
    "CGRequestScreenCaptureAccess",
    "AXIsProcessTrustedWithOptions",
    "kAXTrustedCheckOptionPrompt",
    "x-apple.systempreferences"
]

let expectedHostCliContractCodes: Set<String> = [
    "host_screen_recording_denied",
    "accessibility_denied_or_limited",
    "tcp_54321_unavailable"
]

let parserMessageTokens = [
    "Unknown Vibe Screen Host CLI flag: ",
    "Multiple Vibe Screen Host CLI commands are not supported.",
    "Unknown iOS loopback scenario."
]

func read(_ path: String) throws -> String {
    let url = sourceRoot.appendingPathComponent(path)
    guard FileManager.default.fileExists(atPath: url.path) else {
        throw ContractError.missingFile(path)
    }
    return try String(contentsOf: url, encoding: .utf8)
}

func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    guard condition() else { throw ContractError.violation(message) }
}

func jsonObject(at path: String) throws -> [String: Any] {
    let url = sourceRoot.appendingPathComponent(path)
    guard FileManager.default.fileExists(atPath: url.path) else {
        throw ContractError.missingFile(path)
    }
    let data = try Data(contentsOf: url)
    guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw ContractError.violation(path + " must contain a JSON object")
    }
    return object
}

func requireTokenOrder(_ first: String, before second: String, in source: String) throws {
    guard let firstRange = source.range(of: first) else {
        throw ContractError.violation("missing required token: \(first)")
    }
    guard let secondRange = source.range(of: second) else {
        throw ContractError.violation("missing required token: \(second)")
    }
    try require(
        firstRange.lowerBound < secondRange.lowerBound,
        "\(first) must appear before \(second)"
    )
}

func requireContainsEach(_ tokens: [String], in source: String, context: String) throws {
    for token in tokens {
        try require(source.contains("\"\(token)\""), "\(context) must register \(token)")
    }
}

struct LaunchModeSwitchCase {
    let label: String
    let bodyLines: [String]
    let isDefault: Bool
}

func requireNoPermissionPromptTokens(_ source: String, context: String) throws {
    for token in parseFailurePermissionPromptTokens {
        try require(
            !source.contains(token),
            context + " must not reference permission prompt token " + token
        )
    }
}

enum LaunchModeSwitchLabelKind {
    case command
    case gui
    case defaultEquivalent
    case other
}

func isIdentifierCharacter(_ character: Character) -> Bool {
    character == "_" || character.isLetter || character.isNumber
}

func isWhitespace(_ character: Character) -> Bool {
    character == " " || character == "\t" || character == "\n" || character == "\r"
}

func maskedForSwiftTrivia(_ source: String) -> [Character] {
    var characters = Array(source)
    var index = 0
    var blockCommentDepth = 0

    func mask(_ position: Int) {
        if characters[position] != "\n" && characters[position] != "\r" {
            characters[position] = " "
        }
    }

    while index < characters.count {
        if blockCommentDepth > 0 {
            if index + 1 < characters.count, characters[index] == "/", characters[index + 1] == "*" {
                mask(index)
                mask(index + 1)
                blockCommentDepth += 1
                index += 2
            } else if index + 1 < characters.count, characters[index] == "*", characters[index + 1] == "/" {
                mask(index)
                mask(index + 1)
                blockCommentDepth -= 1
                index += 2
            } else {
                mask(index)
                index += 1
            }
            continue
        }

        if index + 1 < characters.count, characters[index] == "/", characters[index + 1] == "/" {
            mask(index)
            mask(index + 1)
            index += 2
            while index < characters.count, characters[index] != "\n", characters[index] != "\r" {
                mask(index)
                index += 1
            }
            continue
        }

        if index + 1 < characters.count, characters[index] == "/", characters[index + 1] == "*" {
            mask(index)
            mask(index + 1)
            blockCommentDepth = 1
            index += 2
            continue
        }

        if index + 2 < characters.count,
           characters[index] == "\"", characters[index + 1] == "\"", characters[index + 2] == "\"" {
            mask(index)
            mask(index + 1)
            mask(index + 2)
            index += 3
            while index < characters.count {
                if index + 2 < characters.count,
                   characters[index] == "\"", characters[index + 1] == "\"", characters[index + 2] == "\"" {
                    mask(index)
                    mask(index + 1)
                    mask(index + 2)
                    index += 3
                    break
                }
                mask(index)
                index += 1
            }
            continue
        }

        if characters[index] == "#" {
            var delimiterCount = 0
            var delimiterIndex = index
            while delimiterIndex < characters.count, characters[delimiterIndex] == "#" {
                delimiterCount += 1
                delimiterIndex += 1
            }
            if delimiterIndex < characters.count, characters[delimiterIndex] == "\"" {
                let isMultiline = delimiterIndex + 2 < characters.count &&
                    characters[delimiterIndex + 1] == "\"" && characters[delimiterIndex + 2] == "\""
                let openingQuoteCount = isMultiline ? 3 : 1
                for position in index..<(delimiterIndex + openingQuoteCount) {
                    mask(position)
                }
                index = delimiterIndex + openingQuoteCount
                while index < characters.count {
                    if isMultiline {
                        if index + 2 + delimiterCount < characters.count,
                           characters[index] == "\"", characters[index + 1] == "\"", characters[index + 2] == "\"" {
                            var closes = true
                            if delimiterCount > 0 {
                                for offset in 0..<delimiterCount where characters[index + 3 + offset] != "#" {
                                    closes = false
                                    break
                                }
                            }
                            if closes {
                                for position in index...(index + 2 + delimiterCount) {
                                    mask(position)
                                }
                                index += 3 + delimiterCount
                                break
                            }
                        }
                    } else if index + delimiterCount < characters.count, characters[index] == "\"" {
                        var closes = true
                        if delimiterCount > 0 {
                            for offset in 0..<delimiterCount where characters[index + 1 + offset] != "#" {
                                closes = false
                                break
                            }
                        }
                        if closes {
                            for position in index...(index + delimiterCount) {
                                mask(position)
                            }
                            index += 1 + delimiterCount
                            break
                        }
                    }
                    mask(index)
                    index += 1
                }
                continue
            }
        }

        if characters[index] == "\"" {
            mask(index)
            index += 1
            var isEscaped = false
            while index < characters.count {
                let character = characters[index]
                mask(index)
                if character == "\\" && !isEscaped {
                    isEscaped = true
                    index += 1
                    continue
                }
                if character == "\"" && !isEscaped {
                    index += 1
                    break
                }
                isEscaped = false
                index += 1
            }
            continue
        }

        index += 1
    }

    return characters
}

func matchesToken(_ token: String, at index: Int, in characters: [Character]) -> Bool {
    let tokenCharacters = Array(token)
    guard index >= 0, index + tokenCharacters.count <= characters.count else { return false }
    if index > 0, isIdentifierCharacter(characters[index - 1]) { return false }
    if index + tokenCharacters.count < characters.count,
       isIdentifierCharacter(characters[index + tokenCharacters.count]) {
        return false
    }
    for offset in tokenCharacters.indices where characters[index + offset] != tokenCharacters[offset] {
        return false
    }
    return true
}

func braceDelta(_ line: String) -> Int {
    let characters = Array(line)
    return characters.filter { $0 == "{" }.count - characters.filter { $0 == "}" }.count
}

func launchModeSwitchLines(in source: String, context: String) throws -> [String] {
    let lines = String(maskedForSwiftTrivia(source)).split(separator: "\n", omittingEmptySubsequences: false)
        .map(String.init)
    var bodyLines: [String] = []
    var foundSwitch = false
    var depth = 0

    for line in lines {
        if !foundSwitch {
            guard let switchRange = line.range(of: "switch commandLine.launchMode") else { continue }
            foundSwitch = true
            let switchTail = String(line[switchRange.lowerBound...])
            guard switchTail.contains("{") else {
                throw ContractError.violation("\(context) commandLine.launchMode switch must open on its switch line")
            }
            depth = braceDelta(switchTail)
            continue
        }

        let nextDepth = depth + braceDelta(line)
        if depth == 1, nextDepth == 0 {
            return bodyLines
        }
        bodyLines.append(line)
        depth = nextDepth
    }

    if foundSwitch {
        throw ContractError.violation("\(context) commandLine.launchMode switch must close its body")
    }
    throw ContractError.violation("\(context) must switch on commandLine.launchMode")
}

func isCaseLabelStart(_ line: String) -> Bool {
    let trimmed = line.trimmingCharacters(in: .whitespaces)
    if trimmed.hasPrefix("case"),
       trimmed.count > "case".count {
        let afterCase = trimmed.index(trimmed.startIndex, offsetBy: "case".count)
        if isWhitespace(trimmed[afterCase]) { return true }
    }
    if trimmed.hasPrefix("@unknown") {
        let afterUnknown = trimmed.dropFirst("@unknown".count).trimmingCharacters(in: .whitespaces)
        return afterUnknown.hasPrefix("default")
    }
    guard trimmed.hasPrefix("default") else { return false }
    if trimmed.count == "default".count { return true }
    let afterDefault = trimmed.index(trimmed.startIndex, offsetBy: "default".count)
    return !isIdentifierCharacter(trimmed[afterDefault])
}

func hasDepthZeroColon(_ line: String) -> Bool {
    var depth = 0
    for character in line {
        switch character {
        case "(", "[", "{": depth += 1
        case ")", "]", "}": depth -= 1
        case ":":
            if depth == 0 { return true }
        default: break
        }
    }
    return false
}

func switchLabel(in line: String, context: String) throws -> (label: String, tail: String, isDefault: Bool)? {
    let trimmed = line.trimmingCharacters(in: .whitespaces)
    guard isCaseLabelStart(trimmed) else { return nil }
    var depth = 0
    var colonIndex: String.Index?
    scan: for index in trimmed.indices {
        switch trimmed[index] {
        case "(", "[", "{": depth += 1
        case ")", "]", "}": depth -= 1
        case ":":
            if depth == 0 {
                colonIndex = index
                break scan
            }
        default: break
        }
    }
    guard let colonIndex else {
        throw ContractError.violation("\(context) switch label must end with ':'")
    }
    let label = String(trimmed[..<colonIndex]).trimmingCharacters(in: .whitespaces)
    let tail = String(trimmed[trimmed.index(after: colonIndex)...])
    let isDefault = isDefaultLabel(label)
    if !isDefault, !isCaseLabelStart(label) { return nil }
    return (label: label, tail: tail, isDefault: isDefault)
}

func isDefaultLabel(_ label: String) -> Bool {
    let compact = label.split(whereSeparator: isWhitespace).joined(separator: " ")
    return compact == "default" || compact == "@unknown default"
}

func casePatternItems(from label: String) -> [String] {
    var pattern = label.trimmingCharacters(in: .whitespacesAndNewlines)
    if pattern.hasPrefix("case") {
        pattern = String(pattern.dropFirst("case".count))
    }
    var items: [String] = []
    var current = ""
    var depth = 0
    for character in pattern {
        switch character {
        case "(", "[", "{":
            depth += 1
            current.append(character)
        case ")", "]", "}":
            depth -= 1
            current.append(character)
        case "," where depth == 0:
            let item = current.trimmingCharacters(in: .whitespacesAndNewlines)
            if !item.isEmpty { items.append(item) }
            current = ""
        default:
            current.append(character)
        }
    }
    let item = current.trimmingCharacters(in: .whitespacesAndNewlines)
    if !item.isEmpty { items.append(item) }
    return items
}

func basePattern(_ pattern: String) -> String {
    if let whereRange = pattern.range(of: #"\s+where\s+"#, options: .regularExpression) {
        return String(pattern[..<whereRange.lowerBound]).trimmingCharacters(in: .whitespacesAndNewlines)
    }
    return pattern.trimmingCharacters(in: .whitespacesAndNewlines)
}

func withoutWhitespace(_ value: String) -> String {
    String(value.filter { !isWhitespace($0) })
}

func commandAssociatedValue(in pattern: String) -> String? {
    let compact = withoutWhitespace(basePattern(pattern))
    let prefix = ".command("
    guard compact.hasPrefix(prefix), compact.hasSuffix(")") else { return nil }
    let valueStart = compact.index(compact.startIndex, offsetBy: prefix.count)
    return String(compact[valueStart..<compact.index(before: compact.endIndex)])
}

func isWildcardPattern(_ pattern: String) -> Bool {
    let base = withoutWhitespace(basePattern(pattern))
    if base.hasPrefix(".command(") { return false }
    return !base.hasPrefix(".")
}

func isCatchAllCommandPattern(_ pattern: String) -> Bool {
    guard let associatedValue = commandAssociatedValue(in: pattern) else { return false }
    return associatedValue == "_" || !associatedValue.hasPrefix(".")
}

func isExplicitCommandPattern(_ pattern: String) -> Bool {
    guard let associatedValue = commandAssociatedValue(in: pattern) else { return false }
    return associatedValue.hasPrefix(".")
}

func isGUIPattern(_ pattern: String) -> Bool {
    withoutWhitespace(basePattern(pattern)) == ".gui"
}

func labelKind(_ label: String, isDefault: Bool) -> LaunchModeSwitchLabelKind {
    if isDefault { return .defaultEquivalent }
    let patterns = casePatternItems(from: label)
    if patterns.contains(where: isWildcardPattern) { return .defaultEquivalent }
    if patterns.contains(where: isCatchAllCommandPattern) { return .defaultEquivalent }
    if patterns.contains(where: isExplicitCommandPattern) { return .command }
    if patterns.contains(where: isGUIPattern) { return .gui }
    return .other
}

func launchModeSwitchCases(in source: String, context: String) throws -> [LaunchModeSwitchCase] {
    let lines = try launchModeSwitchLines(in: source, context: context)
    var cases: [LaunchModeSwitchCase] = []
    var currentLabel: String?
    var currentIsDefault = false
    var currentBody: [String] = []

    func appendCurrentCase() {
        guard let currentLabel else { return }
        cases.append(LaunchModeSwitchCase(label: currentLabel, bodyLines: currentBody, isDefault: currentIsDefault))
    }

    var index = 0
    while index < lines.count {
        let line = lines[index]
        if isCaseLabelStart(line) {
            var labelLines = [line]
            if !hasDepthZeroColon(line) {
                index += 1
                while index < lines.count {
                    let continuation = lines[index]
                    labelLines.append(continuation)
                    if hasDepthZeroColon(continuation) {
                        break
                    }
                    index += 1
                }
            }
            let combined = labelLines.joined(separator: " ")
            if let label = try switchLabel(in: combined, context: context) {
                appendCurrentCase()
                currentLabel = label.label
                currentIsDefault = label.isDefault
                currentBody = label.tail.isEmpty ? [] : [label.tail]
            }
        } else {
            currentBody.append(line)
        }
        index += 1
    }
    appendCurrentCase()
    return cases
}

func bodyStartsWithExitCall(_ bodyLines: [String]) -> Bool {
    let body = bodyLines.joined(separator: "\n")
    let characters = maskedForSwiftTrivia(body)
    var index = 0
    while index < characters.count, isWhitespace(characters[index]) {
        index += 1
    }
    guard matchesToken("exit", at: index, in: characters) else { return false }
    index += "exit".count
    while index < characters.count, isWhitespace(characters[index]) {
        index += 1
    }
    return index < characters.count && characters[index] == "("
}

func bodyContainsBreak(_ bodyLines: [String]) -> Bool {
    let body = bodyLines.joined(separator: "\n")
    let characters = maskedForSwiftTrivia(body)
    var index = 0
    while index < characters.count {
        if matchesToken("break", at: index, in: characters) { return true }
        index += 1
    }
    return false
}

func verifyLaunchModeSwitchContract(source: String, context: String) throws {
    let cases = try launchModeSwitchCases(in: source, context: context)
    try require(!cases.isEmpty, "\(context) commandLine.launchMode switch must declare explicit cases")

    var foundCommandCase = false
    var foundGUICase = false
    for switchCase in cases {
        switch labelKind(switchCase.label, isDefault: switchCase.isDefault) {
        case .defaultEquivalent:
            throw ContractError.violation(
                "\(context) commandLine.launchMode switch must not use default-equivalent cases; new commands must be explicit"
            )
        case .command:
            foundCommandCase = true
            try require(
                bodyStartsWithExitCall(switchCase.bodyLines),
                "\(context) \(switchCase.label.trimmingCharacters(in: .whitespacesAndNewlines)) must immediately call exit(...)"
            )
            try require(
                !bodyContainsBreak(switchCase.bodyLines),
                "\(context) \(switchCase.label.trimmingCharacters(in: .whitespacesAndNewlines)) must not use break"
            )
        case .gui:
            foundGUICase = true
        case .other:
            throw ContractError.violation(
                "\(context) \(switchCase.label.trimmingCharacters(in: .whitespacesAndNewlines)) must be an explicit command or GUI case"
            )
        }
    }

    try require(foundCommandCase, "\(context) commandLine.launchMode switch must handle command cases explicitly")
    try require(foundGUICase, "\(context) commandLine.launchMode switch must keep an explicit GUI case")
}

func requireStaticFixturePasses(_ source: String, context: String) throws {
    do {
        try verifyLaunchModeSwitchContract(source: source, context: context)
    } catch {
        throw ContractError.violation("expected fixture to pass (\(context)): \(error)")
    }
}

func requireStaticFixtureFails(_ source: String, context: String) throws {
    do {
        try verifyLaunchModeSwitchContract(source: source, context: context)
    } catch ContractError.violation {
        return
    } catch {
        throw ContractError.violation("expected fixture violation (\(context)), got: \(error)")
    }
    throw ContractError.violation("expected fixture to fail (\(context))")
}

func verifyLaunchModeSwitchFixtures() throws {
    let valid = #"""
    let commandLine = HostCommandLine.parse(arguments: CommandLine.arguments)
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    case .command(.iOSLoopback(let expectsInvalidTarget)):
        exit(IOSClientLoopbackHost.run(expectsInvalidTarget: expectsInvalidTarget)
            ? EXIT_SUCCESS
            : EXIT_FAILURE)
    case .gui:
        break
    }
    let app = NSApplication.shared
    """#
    try requireStaticFixturePasses(valid, context: "valid launch mode switch fixture")

    let missingExit = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        _ = HostSelfTest.run()
    case .gui:
        break
    }
    """#
    try requireStaticFixtureFails(missingExit, context: "missing command exit fixture")

    let commandBreak = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
        break
    case .gui:
        break
    }
    """#
    try requireStaticFixtureFails(commandBreak, context: "command break fixture")

    let defaultBreak = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    default:
        break
    }
    """#
    try requireStaticFixtureFails(defaultBreak, context: "default break fixture")

    let wildcardCase = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    case _:
        break
    }
    """#
    try requireStaticFixtureFails(wildcardCase, context: "wildcard default-equivalent fixture")

    let guiAndWildcardCase = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    case .gui, _:
        break
    }
    """#
    try requireStaticFixtureFails(guiAndWildcardCase, context: "GUI plus wildcard default-equivalent fixture")

    let wildcardWhereCase = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    case _ where true:
        break
    }
    """#
    try requireStaticFixtureFails(wildcardWhereCase, context: "wildcard where default-equivalent fixture")

    let unknownDefaultCase = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    @unknown default:
        break
    }
    """#
    try requireStaticFixtureFails(unknownDefaultCase, context: "unknown default fixture")

    let unknownDefaultWhitespaceCase = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    @unknown   default:
        break
    }
    """#
    try requireStaticFixtureFails(unknownDefaultWhitespaceCase, context: "unknown default whitespace fixture")

    let unknownDefaultTabCase = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    @unknown	default:
        break
    }
    """#
    try requireStaticFixtureFails(unknownDefaultTabCase, context: "unknown default tab fixture")

    let catchAllCommandCase = #"""
    switch commandLine.launchMode {
    case .command(_):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    case .gui:
        break
    }
    """#
    try requireStaticFixtureFails(catchAllCommandCase, context: "catch-all command fixture")

    let catchAllLetCase = #"""
    switch commandLine.launchMode {
    case let mode:
        break
    }
    """#
    try requireStaticFixtureFails(catchAllLetCase, context: "catch-all let case fixture")

    let guiAndLetCase = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    case .gui, let mode:
        break
    }
    """#
    try requireStaticFixtureFails(guiAndLetCase, context: "GUI plus let catch-all fixture")

    let commandAndLetCase = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest), let mode:
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    case .gui:
        break
    }
    """#
    try requireStaticFixtureFails(commandAndLetCase, context: "command plus let catch-all fixture")

    let missingIOSLoopbackExit = #"""
    switch commandLine.launchMode {
    case .command(.iOSLoopback(let expectsInvalidTarget)):
        _ = IOSClientLoopbackHost.run(expectsInvalidTarget: expectsInvalidTarget)
    case .gui:
        break
    }
    """#
    try requireStaticFixtureFails(missingIOSLoopbackExit, context: "iOS loopback missing exit fixture")

    let triviaMasked = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        // default: this comment must not be treated as a case label
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
        let s = "break inside string"
    case .gui:
        break
    }
    """#
    try requireStaticFixturePasses(triviaMasked, context: "trivia masking fixture")

    let defaultsSetInBody = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
        defaults.set(true, forKey: "flag")
    case .gui:
        break
    }
    """#
    try requireStaticFixturePasses(defaultsSetInBody, context: "defaults.set word boundary fixture")

    let colonInCaseTail = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    case .gui: let mode = true ? 1 : 2
        break
    }
    """#
    try requireStaticFixturePasses(colonInCaseTail, context: "depth-0 colon scan fixture")

    let multiLineCaseLabel = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest),
         .command(.transportSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    case .gui:
        break
    }
    """#
    try requireStaticFixturePasses(multiLineCaseLabel, context: "multi-line case label fixture")

    let tabbedCaseLabel = #"""
    switch commandLine.launchMode {
    case	.command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    case .gui:
        break
    }
    """#
    try requireStaticFixturePasses(tabbedCaseLabel, context: "tabbed case label fixture")

    let multiLineStringTrivia = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
        let message = """
        default:
        break
        """
    case .gui:
        break
    }
    """#
    try requireStaticFixturePasses(multiLineStringTrivia, context: "multi-line string trivia fixture")

    let rawStringTrivia = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
        let message = #"default: break"#
    case .gui:
        break
    }
    """#
    try requireStaticFixturePasses(rawStringTrivia, context: "raw string trivia fixture")

    let missingGUICase = #"""
    switch commandLine.launchMode {
    case .command(.hostSelfTest):
        exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
    }
    """#
    try requireStaticFixtureFails(missingGUICase, context: "missing GUI case fixture")

    let missingSwitch = #"""
    let commandLine = HostCommandLine.parse(arguments: CommandLine.arguments)
    if case .gui = commandLine.launchMode {
        break
    }
    """#
    try requireStaticFixtureFails(missingSwitch, context: "missing switch fixture")
}

@discardableResult
func run(_ executable: String, _ arguments: [String]) throws -> String {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = arguments
    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = pipe
    try process.run()
    process.waitUntilExit()
    let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    guard process.terminationStatus == 0 else {
        throw ContractError.commandFailed(([executable] + arguments).joined(separator: " "), process.terminationStatus, output)
    }
    return output
}

func verifyParserBehavior() throws {
    let temporaryDirectory = FileManager.default.temporaryDirectory
        .appendingPathComponent("vibescreen-host-cli-contract-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: temporaryDirectory) }

    let harness = #"""
    import Foundation

    func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else {
            FileHandle.standardError.write(Data((message + "\n").utf8))
            exit(1)
        }
    }

    func parse(_ arguments: [String], environment: [String: String] = [:]) -> HostCommandLine.ParseResult {
        HostCommandLine.parse(arguments: arguments, environment: environment)
    }

    let unknownSelfTest = parse(["Vibe Screen", "--self-test"])
    require(!unknownSelfTest.canLaunch, "--self-test must fail closed")
    require(
        unknownSelfTest.errorMessage == "Unknown Vibe Screen Host CLI flag: --self-test",
        "--self-test must report the unknown flag"
    )

    let bareDoubleDash = parse(["Vibe Screen", "--"])
    require(!bareDoubleDash.canLaunch, "bare -- must fail closed")
    require(
        bareDoubleDash.errorMessage == "Unknown Vibe Screen Host CLI flag: --",
        "bare -- must report the unknown flag"
    )

    let valuedCommand = parse(["Vibe Screen", "--host-self-test=foo"])
    require(!valuedCommand.canLaunch, "known command with value syntax must fail closed")
    require(
        valuedCommand.errorMessage == "Unknown Vibe Screen Host CLI flag: --host-self-test=foo",
        "known command with value syntax must report the unknown flag"
    )

    let knownSelfTest = parse(["Vibe Screen", "--protocol-v1-self-test"])
    require(knownSelfTest.canLaunch, "known self-test flag must be accepted")
    require(
        knownSelfTest.launchMode == .command(.protocolV1SelfTest),
        "known self-test flag must choose Protocol v1 self-test"
    )

    let gui = parse(["Vibe Screen"])
    require(gui.canLaunch, "empty argument list after executable must be accepted")
    require(gui.launchMode == .gui, "empty argument list after executable must choose GUI mode")

    let singleDash = parse(["Vibe Screen", "-NSDocumentRevisionsDebugMode", "YES"])
    require(singleDash.canLaunch, "single-dash macOS injected arguments must not be rejected")
    require(singleDash.launchMode == .gui, "single-dash macOS injected arguments must keep GUI mode")

    let guiFlag = parse(["Vibe Screen", "--prefer-cgdisplaystream"])
    require(guiFlag.canLaunch, "known GUI double-dash flags must not be rejected")
    require(guiFlag.launchMode == .gui, "known GUI double-dash flags must keep GUI mode")

    let multipleCommands = parse(["Vibe Screen", "--host-self-test", "--issue-phase3-internet-lease"])
    require(!multipleCommands.canLaunch, "multiple CLI commands must fail closed")

    let duplicateCommand = parse(["Vibe Screen", "--host-self-test", "--host-self-test"])
    require(!duplicateCommand.canLaunch, "duplicate CLI commands must fail closed")

    let loopback = parse(
        ["Vibe Screen"],
        environment: ["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO": "invalid-target"]
    )
    require(loopback.canLaunch, "known iOS loopback scenario must be accepted")
    require(
        loopback.launchMode == .command(.iOSLoopback(expectsInvalidTarget: true)),
        "known iOS loopback scenario must choose loopback command"
    )

    let unknownLoopback = parse(
        ["Vibe Screen"],
        environment: ["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO": "other"]
    )
    require(!unknownLoopback.canLaunch, "unknown iOS loopback scenario must fail closed")

    let emptyLoopback = parse(
        ["Vibe Screen"],
        environment: ["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO": ""]
    )
    require(!emptyLoopback.canLaunch, "empty iOS loopback scenario must fail closed")

    let loopbackConflict = parse(
        ["Vibe Screen", "--host-self-test"],
        environment: ["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO": "lifecycle"]
    )
    require(!loopbackConflict.canLaunch, "CLI command and iOS loopback environment must fail closed")

    print("PASS HostCommandLine behavior harness")
    """#

    let harnessURL = temporaryDirectory.appendingPathComponent("main.swift")
    let binaryURL = temporaryDirectory.appendingPathComponent("host-cli-contract-test")
    try harness.write(to: harnessURL, atomically: true, encoding: .utf8)
    try run("/usr/bin/env", [
        "swiftc",
        sourceRoot.appendingPathComponent(parserPath).path,
        harnessURL.path,
        "-o",
        binaryURL.path
    ])
    _ = try run(binaryURL.path, [])
}

func verifyPreGuiParseFailureContract(main: String, parser: String) throws {
    try requireTokenOrder(
        "HostCommandLine.parse(arguments: CommandLine.arguments)",
        before: "if let errorMessage = commandLine.errorMessage",
        in: main
    )
    try requireTokenOrder(
        "if let errorMessage = commandLine.errorMessage",
        before: "switch commandLine.launchMode",
        in: main
    )
    try requireTokenOrder("FileHandle.standardError.write", before: "exit(EXIT_FAILURE)", in: main)
    try requireTokenOrder("exit(EXIT_FAILURE)", before: "switch commandLine.launchMode", in: main)
    try requireTokenOrder("exit(EXIT_FAILURE)", before: "NSApplication.shared", in: main)
    try requireTokenOrder("exit(EXIT_FAILURE)", before: "AppDelegate()", in: main)

    guard let switchRange = main.range(of: "switch commandLine.launchMode") else {
        throw ContractError.violation("main.swift must switch on commandLine.launchMode")
    }
    let preSwitchMain = String(main[..<switchRange.lowerBound])
    try requireNoPermissionPromptTokens(preSwitchMain, context: "main.swift parse-failure block")
    try requireNoPermissionPromptTokens(parser, context: "HostCommandLine parser")
}

func verifyActionableErrorHostCliContracts(manifest: [String: Any], parser: String) throws {
    guard let states = manifest["states"] as? [[String: Any]] else {
        throw ContractError.violation("\(actionableErrorStatesPath) states must be an array")
    }
    var foundCodes = Set<String>()
    for state in states {
        guard
            let contract = state["contract"] as? [String: Any],
            let code = contract["code"] as? String,
            expectedHostCliContractCodes.contains(code)
        else { continue }
        foundCodes.insert(code)
        guard let hostCliContract = state["host_cli_contract"] as? [String: Any] else {
            throw ContractError.violation("\(code) must declare host_cli_contract")
        }
        try require(
            hostCliContract["pre_gui_fail_closed"] as? Bool == true,
            "\(code).host_cli_contract.pre_gui_fail_closed must be true"
        )
        try require(
            hostCliContract["exit_code"] as? String == "EXIT_FAILURE",
            "\(code).host_cli_contract.exit_code must be EXIT_FAILURE"
        )
        try require(
            hostCliContract["no_permission_prompt_on_parse_failure"] as? Bool == true,
            "\(code).host_cli_contract.no_permission_prompt_on_parse_failure must be true"
        )
        guard let messages = hostCliContract["stderr_error_messages"] as? [String] else {
            throw ContractError.violation("\(code).host_cli_contract.stderr_error_messages must be string array")
        }
        try require(
            messages == expectedParseFailureMessages,
            "\(code).host_cli_contract.stderr_error_messages must match the stable parser errors"
        )
        for token in parserMessageTokens {
            try require(parser.contains(token), "HostCommandLine parser must contain \(token)")
        }
    }

    let missing = expectedHostCliContractCodes.subtracting(foundCodes).sorted()
    try require(missing.isEmpty, "missing Host CLI manifest contract(s): " + missing.joined(separator: ", "))
}

do {
    let main = try read(mainPath)
    let parser = try read(parserPath)
    let actionableErrorStates = try jsonObject(at: actionableErrorStatesPath)

    try require(
        main.contains("HostCommandLine.parse(arguments: CommandLine.arguments)"),
        "main.swift must parse arguments through HostCommandLine before launch"
    )
    try require(
        main.contains("case .command(.iOSLoopback(let expectsInvalidTarget))"),
        "main.swift must dispatch iOS loopback mode from HostCommandLine"
    )
    try require(
        main.contains("FileHandle.standardError.write"),
        "main.swift must print CLI parse failures to stderr"
    )
    try require(
        main.contains("exit(EXIT_FAILURE)"),
        "main.swift must fail closed for rejected CLI arguments"
    )
    try requireTokenOrder("HostCommandLine.parse(arguments: CommandLine.arguments)", before: "NSApplication.shared", in: main)
    try requireTokenOrder("HostCommandLine.parse(arguments: CommandLine.arguments)", before: "AppDelegate()", in: main)
    try requireTokenOrder("iOSLoopback", before: "NSApplication.shared", in: main)
    try require(
        !main.contains("CommandLine.arguments.contains(\"--"),
        "main.swift must not bypass centralized HostCommandLine parsing for double-dash flags"
    )
    try verifyLaunchModeSwitchContract(source: main, context: mainPath)

    try requireContainsEach(expectedCommandFlags, in: parser, context: "HostCommandLine command flags")
    try requireContainsEach(expectedGuiFlags, in: parser, context: "HostCommandLine GUI flags")
    try require(
        parser.contains("VIBE_SCREEN_IOS_LOOPBACK_SCENARIO") &&
            parser.contains("case \"lifecycle\"") &&
            parser.contains("case \"invalid-target\""),
        "HostCommandLine must validate iOS loopback environment before GUI launch"
    )
    try require(
        !parser.contains("\"--self-test\""),
        "--self-test must stay unsupported so it fails closed instead of launching GUI"
    )
    try require(
        parser.contains("argument.hasPrefix(\"--\")") && !parser.contains("argument.hasPrefix(\"-\") &&"),
        "HostCommandLine must reject unknown double-dash flags without blocking single-dash macOS arguments"
    )

    try verifyPreGuiParseFailureContract(main: main, parser: parser)
    try verifyActionableErrorHostCliContracts(manifest: actionableErrorStates, parser: parser)
    try verifyLaunchModeSwitchFixtures()
    try verifyParserBehavior()

    print("PASS macOS Host CLI contract")
} catch {
    fputs("FAIL macOS Host CLI contract: \(error)\n", stderr)
    exit(1)
}
