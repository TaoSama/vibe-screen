import Foundation
import AppKit

if CommandLine.arguments.contains("--issue-phase3-internet-lease") {
    exit(InternetSessionLeaseCLI.run() ? EXIT_SUCCESS : EXIT_FAILURE)
}

print("🚀 Telemachus starting...")

if CommandLine.arguments.contains("--transport-self-test") {
    exit(TransportSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
}

if CommandLine.arguments.contains("--reliability-self-test") {
    exit(ReliabilityCoreSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
}

if CommandLine.arguments.contains("--protocol-v1-self-test") {
    exit(ProtocolV1SelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
}

if CommandLine.arguments.contains("--host-self-test") {
    exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
}

if CommandLine.arguments.contains("--phase3-internet-self-test") {
    exit(InternetTransportSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
}

if CommandLine.arguments.contains("--phase3-internet-lease-self-test") {
    exit(InternetSessionLeaseSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
}

if CommandLine.arguments.contains("--phase3-webrtc-loopback-self-test") {
    exit(ProductionWebRTCEngineSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
}

if CommandLine.arguments.contains("--phase3-webrtc-signaling-self-test") {
    exit(ProductionWebRTCEngineSelfTest.runWithSignalingService() ? EXIT_SUCCESS : EXIT_FAILURE)
}

if CommandLine.arguments.contains("--phase3-product-signaling-self-test") {
    exit(InternetProductSessionSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
}

if CommandLine.arguments.contains("--phase3-product-android-interop-host") {
    exit(InternetProductExternalHostE2E.run() ? EXIT_SUCCESS : EXIT_FAILURE)
}

if let scenario = ProcessInfo.processInfo.environment["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO"] {
    guard scenario == "lifecycle" || scenario == "invalid-target" else {
        FileHandle.standardError.write(Data("Unknown iOS loopback scenario.\n".utf8))
        exit(EXIT_FAILURE)
    }
    exit(IOSClientLoopbackHost.run(expectsInvalidTarget: scenario == "invalid-target")
        ? EXIT_SUCCESS
        : EXIT_FAILURE)
}

// Entry point
let app = NSApplication.shared

// Setup main menu for keyboard shortcuts (Command+Q, etc.)
let mainMenu = NSMenu()

// App menu
let appMenu = NSMenu()
let appMenuItem = NSMenuItem()
appMenuItem.submenu = appMenu
appMenu.addItem(NSMenuItem(title: "About Telemachus", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: ""))
appMenu.addItem(NSMenuItem.separator())
appMenu.addItem(NSMenuItem(title: "Quit Telemachus", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
mainMenu.addItem(appMenuItem)

// Edit menu (for standard text editing shortcuts)
let editMenu = NSMenu(title: "Edit")
let editMenuItem = NSMenuItem()
editMenuItem.submenu = editMenu
editMenu.addItem(NSMenuItem(title: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x"))
editMenu.addItem(NSMenuItem(title: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c"))
editMenu.addItem(NSMenuItem(title: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v"))
editMenu.addItem(NSMenuItem(title: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a"))
mainMenu.addItem(editMenuItem)

app.mainMenu = mainMenu

let delegate = MainActor.assumeIsolated { AppDelegate() }

app.setActivationPolicy(.regular)

app.delegate = delegate
app.run()
