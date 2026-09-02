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

do {
    let main = try read(mainPath)
    let parser = try read(parserPath)

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

    try verifyParserBehavior()

    print("PASS macOS Host CLI contract")
} catch {
    fputs("FAIL macOS Host CLI contract: \(error)\n", stderr)
    exit(1)
}
