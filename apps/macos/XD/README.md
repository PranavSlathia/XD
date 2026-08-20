# XD for macOS

Native SwiftUI client for the private Domain Hunter engine. It targets macOS 14,
runs as a menu-bar utility, and opens the full three-column review instrument only
when requested or when Today contains attention items.

## Safety contract

- Dell/PostgreSQL remains authoritative.
- The device token lives in Keychain; the server stores only its hash.
- Cached SwiftData evidence is visibly stale and cannot be mutated offline.
- Review buttons call guarded API v1 endpoints. Ready can still be rejected by
  the server when a required gate is pending or failed.
- Operator controls create only typed PostgreSQL jobs. There is no shell, Docker,
  purchase, registration, bid, auction, or backorder surface.

## Development

Full Xcode is required for final builds, SwiftUI previews, signing, login-item
validation, and installation. With matching Xcode tools selected:

```bash
swift test
swift run XD --demo
./scripts/build-app.sh
```

`--demo` uses deterministic local evidence and an in-memory SwiftData cache. It
never contacts the Dell server.

The bundle script creates an ad-hoc-signed universal app at `dist/XD.app` for
personal testing. Production installation on both Macs should use a stable
Developer ID/personal signing identity and should happen only after backend
pairing plus the Vulture parity gates in `docs/XD-OPERATIONS.md`.

## Structure

- `XDCore` — Codable API contracts, Keychain/SwiftData services, app store,
  notification/event behavior, and SwiftUI screens.
- `XD` — menu-bar scene, quiet window coordinator, and app dependency graph.
- `Design/selected-option-3.png` — selected Evidence Sequencer target.
- `Tests/XDCoreTests` — lane/readiness/config/safety/decoding tests.

