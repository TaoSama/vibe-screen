// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "VibeScreenIOS",
    platforms: [
        .iOS(.v17),
        .macOS(.v14),
    ],
    products: [
        .library(name: "VibeScreenProtocol", targets: ["VibeScreenProtocol"]),
        .library(name: "VibeScreenCore", targets: ["VibeScreenCore"]),
        .library(name: "VibeScreenVideo", targets: ["VibeScreenVideo"]),
        .executable(name: "vibescreen-ios-selftest", targets: ["VibeScreenIOSSelfTest"]),
        .executable(
            name: "vibescreen-mac-host-loopback",
            targets: ["VibeScreenMacHostLoopback"]
        ),
    ],
    dependencies: [
        .package(
            url: "https://github.com/apple/swift-protobuf.git",
            revision: "c6fe6442e6a64250495669325044052e113e990c"
        ),
    ],
    targets: [
        .target(
            name: "VibeScreenProtocol",
            dependencies: [.product(name: "SwiftProtobuf", package: "swift-protobuf")]
        ),
        .target(
            name: "VibeScreenCore",
            dependencies: ["VibeScreenProtocol"]
        ),
        .target(
            name: "VibeScreenVideo",
            dependencies: ["VibeScreenCore"],
            linkerSettings: [
                .linkedFramework("CoreMedia"),
                .linkedFramework("VideoToolbox"),
            ]
        ),
        .executableTarget(
            name: "VibeScreenIOSSelfTest",
            dependencies: ["VibeScreenCore", "VibeScreenProtocol", "VibeScreenVideo"]
        ),
        .executableTarget(
            name: "VibeScreenMacHostLoopback",
            dependencies: ["VibeScreenCore", "VibeScreenProtocol"]
        ),
        .testTarget(
            name: "VibeScreenCoreTests",
            dependencies: ["VibeScreenCore", "VibeScreenProtocol"]
        ),
    ]
)
