#!/usr/bin/env bash
set -euo pipefail

app_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$app_root"

swift build -c release --arch arm64 --arch x86_64

binary_path="$app_root/.build/apple/Products/Release/XD"
if [[ ! -x "$binary_path" ]]; then
  printf 'Universal XD binary not found at %s\n' "$binary_path" >&2
  exit 1
fi

bundle_path="$app_root/dist/XD.app"
if [[ -e "$bundle_path" ]]; then
  rm -rf "$bundle_path"
fi
mkdir -p "$bundle_path/Contents/MacOS" "$bundle_path/Contents/Resources"
cp "$binary_path" "$bundle_path/Contents/MacOS/XD"
cp "$app_root/Resources/Info.plist" "$bundle_path/Contents/Info.plist"
codesign --force --deep --sign - "$bundle_path"

printf 'Built %s\n' "$bundle_path"
lipo -archs "$bundle_path/Contents/MacOS/XD"
codesign --verify --deep --strict "$bundle_path"

