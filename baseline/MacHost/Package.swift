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
            targets: ["Telemachus"]),
        .library(
            name: "VibeScreenProtocol",
            targets: ["VibeScreenProtocol"])
    ],
    dependencies: [
        .package(
            url: "https://github.com/stasel/WebRTC.git",
            exact: "150.0.0"
        ),
        .package(
            url: "https://github.com/apple/swift-protobuf.git",
            revision: "c6fe6442e6a64250495669325044052e113e990c"
        )
    ],
    targets: [
        .target(
            name: "VibeScreenProtocol",
            dependencies: [
                .product(name: "SwiftProtobuf", package: "swift-protobuf")
            ],
            path: "Protocol/Sources/VibeScreenProtocol"
        ),
        .executableTarget(
            name: "Telemachus",
            dependencies: [
                "VibeScreenProtocol",
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
                "VibeScreenProtocol",
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
