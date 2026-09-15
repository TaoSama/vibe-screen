#!/usr/bin/env swift
import Cocoa
import CoreImage
import Foundation

// Clean signal handling
signal(SIGINT) { _ in exit(0) }
signal(SIGTERM) { _ in exit(0) }

// Fail-closed check: Unknown or extra command-line arguments are strictly forbidden.
// Python argparse owns all CLI parsing; qr_presenter.swift accepts configuration solely via stdin JSON or stdin payload.
if CommandLine.arguments.count > 1 {
    fputs("error: qr_presenter.swift accepts no command-line arguments; pass configuration via stdin JSON\n", stderr)
    exit(2)
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    let payload: String
    let timeoutSeconds: Double?
    let scale: CGFloat

    init(payload: String, timeoutSeconds: Double?, scale: CGFloat) {
        self.payload = payload
        self.timeoutSeconds = timeoutSeconds
        self.scale = scale
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let data = payload.data(using: .utf8),
              let filter = CIFilter(name: "CIQRCodeGenerator") else {
            fputs("error: Failed to initialize CIQRCodeGenerator\n", stderr)
            exit(1)
        }
        filter.setValue(data, forKey: "inputMessage")
        filter.setValue("M", forKey: "inputCorrectionLevel")

        guard let outputImage = filter.outputImage else {
            fputs("error: Failed to generate QR code output image\n", stderr)
            exit(1)
        }

        let transform = CGAffineTransform(scaleX: scale, y: scale)
        let scaledImage = outputImage.transformed(by: transform)

        let rep = NSCIImageRep(ciImage: scaledImage)
        let nsImage = NSImage(size: rep.size)
        nsImage.addRepresentation(rep)

        let padding: CGFloat = 40.0
        let windowWidth: CGFloat = max(400, rep.size.width + padding * 2)
        let windowHeight: CGFloat = max(400, rep.size.height + padding * 2)
        let screenRect = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 800, height: 600)
        let windowRect = NSRect(
            x: screenRect.midX - windowWidth / 2,
            y: screenRect.midY - windowHeight / 2,
            width: windowWidth,
            height: windowHeight
        )

        window = NSWindow(
            contentRect: windowRect,
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Vibe Screen QR Code Presenter"
        window.backgroundColor = .white

        let imageView = NSImageView(frame: NSRect(
            x: (windowWidth - rep.size.width) / 2,
            y: (windowHeight - rep.size.height) / 2,
            width: rep.size.width,
            height: rep.size.height
        ))
        imageView.image = nsImage
        imageView.imageScaling = .scaleProportionallyUpOrDown
        window.contentView?.addSubview(imageView)

        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)

        print("QR_PRESENTER_READY")
        fflush(stdout)

        if let timeout = timeoutSeconds, timeout > 0 {
            DispatchQueue.main.asyncAfter(deadline: .now() + timeout) {
                NSApplication.shared.terminate(nil)
            }
        }
    }
}

// Read configuration from standard input
guard let firstLine = readLine(strippingNewline: true), !firstLine.isEmpty else {
    fputs("error: No configuration or payload provided via standard input\n", stderr)
    exit(1)
}

var payload = ""
var timeoutSeconds: Double? = nil
var scale: CGFloat = 16.0
var checkOnly = false

var rawConfig = firstLine
if let firstData = firstLine.data(using: .utf8),
   (try? JSONSerialization.jsonObject(with: firstData, options: [])) == nil {
    // If firstLine isn't standalone JSON, try accumulating if it looks like multi-line JSON
    if firstLine.trimmingCharacters(in: .whitespaces).hasPrefix("{") {
        while let nextLine = readLine(strippingNewline: false) {
            rawConfig += nextLine
            if let data = rawConfig.data(using: .utf8),
               (try? JSONSerialization.jsonObject(with: data, options: [])) != nil {
                break
            }
        }
    }
}

if let configData = rawConfig.data(using: .utf8),
   let json = try? JSONSerialization.jsonObject(with: configData, options: []) as? [String: Any] {
    if let p = json["payload"] as? String {
        payload = p
    }
    if let t = json["timeout_seconds"] as? Double, t > 0 {
        timeoutSeconds = t
    }
    if let s = json["scale"] as? Double, s > 0 {
        scale = CGFloat(s)
    }
    if let c = json["check"] as? Bool {
        checkOnly = c
    }
    if let action = json["action"] as? String, action == "check" {
        checkOnly = true
    }
} else {
    // Plain string payload
    payload = firstLine.trimmingCharacters(in: .whitespacesAndNewlines)
}

if checkOnly {
    let testPayload = payload.isEmpty ? "vibescreen://test-check" : payload
    guard let data = testPayload.data(using: .utf8),
          let filter = CIFilter(name: "CIQRCodeGenerator") else {
        fputs("error: Failed to initialize CIQRCodeGenerator\n", stderr)
        exit(1)
    }
    filter.setValue(data, forKey: "inputMessage")
    filter.setValue("M", forKey: "inputCorrectionLevel")
    guard let outputImage = filter.outputImage else {
        fputs("error: Failed to generate QR code output image\n", stderr)
        exit(1)
    }
    print("CHECK_PASS extent=\(outputImage.extent.size.width)x\(outputImage.extent.size.height)")
    fflush(stdout)
    exit(0)
}

if payload.isEmpty {
    fputs("error: QR payload is empty\n", stderr)
    exit(1)
}

// Monitor stdin in background: when stdin closes (EOF), terminate window cleanly
DispatchQueue.global(qos: .background).async {
    while let _ = readLine(strippingNewline: false) {}
    DispatchQueue.main.async {
        NSApplication.shared.terminate(nil)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate(payload: payload, timeoutSeconds: timeoutSeconds, scale: scale)
app.delegate = delegate
app.run()
