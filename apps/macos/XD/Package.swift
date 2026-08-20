// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "XD",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "XD", targets: ["XD"]),
        .library(name: "XDCore", targets: ["XDCore"]),
    ],
    targets: [
        .target(
            name: "XDCore",
            path: "Sources/XDCore"
        ),
        .executableTarget(
            name: "XD",
            dependencies: ["XDCore"],
            path: "Sources/XD"
        ),
        .testTarget(
            name: "XDCoreTests",
            dependencies: ["XDCore"],
            path: "Tests/XDCoreTests"
        ),
    ]
)
