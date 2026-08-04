// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Telemachus",
    platforms: [
        // Floor is ScreenCaptureKit basics (12.3) + OSAllocatedUnfairLock /
        // SCStreamConfiguration.capturesAudio (13.0). CGVirtualDisplay is a
        // private API present well before 13 — it does NOT require 14.
        .macOS(.v13)
    ],
    products: [
        .executable(
            name: "Telemachus",
            targets: ["Telemachus"])
    ],
    dependencies: [
        .package(
            url: "https://github.com/stasel/WebRTC.git",
            exact: "150.0.0"
        )
    ],
    targets: [
        .executableTarget(
            name: "Telemachus",
            dependencies: [
                .product(name: "WebRTC", package: "WebRTC")
            ],
            path: "Sources",
            resources: [
                .copy("Phase3/InternetTransport/ThirdParty")
            ],
            cSettings: [
                .unsafeFlags(["-I", "Sources"])
            ],
            swiftSettings: [
                .unsafeFlags(["-Xcc", "-fmodule-map-file=Sources/module.modulemap"])
            ],
            linkerSettings: [
                .unsafeFlags(["-Xlinker", "-rpath", "-Xlinker", "@executable_path/../Frameworks"])
            ]),
        .testTarget(
            name: "TelemachusTests",
            dependencies: [
                "Telemachus",
                .product(name: "WebRTC", package: "WebRTC")
            ],
            path: "Tests/TelemachusTests",
            cSettings: [
                .unsafeFlags(["-I", "Sources"])
            ],
            swiftSettings: [
                .unsafeFlags(["-Xcc", "-fmodule-map-file=Sources/module.modulemap"])
            ]
        )
    ]
)
