import Foundation
import AppKit

let commandLine = HostCommandLine.parse(arguments: CommandLine.arguments)
if let errorMessage = commandLine.errorMessage {
    FileHandle.standardError.write(Data((errorMessage + "\n").utf8))
    exit(EXIT_FAILURE)
}

switch commandLine.launchMode {
case .command(.issuePhase3InternetLease):
    exit(InternetSessionLeaseCLI.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.transportSelfTest):
    exit(TransportSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.reliabilitySelfTest):
    exit(ReliabilityCoreSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.protocolV1SelfTest):
    exit(ProtocolV1SelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.videoEncoderSelfTest):
    exit(VideoEncoderSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.audioCaptureSelfTest):
    exit(AudioCaptureSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.hostSelfTest):
    exit(HostSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.phase3InternetSelfTest):
    exit(InternetTransportSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.phase3InternetLeaseSelfTest):
    exit(InternetSessionLeaseSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.phase3WebRTCLoopbackSelfTest):
    exit(ProductionWebRTCEngineSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.phase3WebRTCSignalingSelfTest):
    exit(ProductionWebRTCEngineSelfTest.runWithSignalingService() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.phase3ProductSignalingSelfTest):
    exit(InternetProductSessionSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.phase3ProductAndroidInteropHost):
    exit(InternetProductExternalHostE2E.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.phase3RealMediaSelfTest):
    exit(InternetProductSessionRealMediaSelfTest.run() ? EXIT_SUCCESS : EXIT_FAILURE)
case .command(.iOSLoopback(let expectsInvalidTarget)):
    exit(IOSClientLoopbackHost.run(expectsInvalidTarget: expectsInvalidTarget)
        ? EXIT_SUCCESS
        : EXIT_FAILURE)
case .gui:
    break
}

print("🚀 Vibe Screen starting...")

// Entry point
let app = NSApplication.shared

// Setup main menu for keyboard shortcuts (Command+Q, etc.)
let mainMenu = NSMenu()

// App menu
let appMenu = NSMenu()
let appMenuItem = NSMenuItem()
appMenuItem.submenu = appMenu
appMenu.addItem(NSMenuItem(title: "About Vibe Screen", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: ""))
appMenu.addItem(NSMenuItem.separator())
appMenu.addItem(NSMenuItem(title: "Quit Vibe Screen", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
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
