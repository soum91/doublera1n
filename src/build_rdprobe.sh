#!/usr/bin/env bash
# Build only the read-only USB transport probe, leaving existing rdsetup untouched.
set -euo pipefail
cd "$(dirname "$0")/.."
sdk=$(xcrun --sdk iphoneos --show-sdk-path)
mkdir -p payload/setup
xcrun clang -target arm64-apple-ios17.0 -isysroot "$sdk" -O2 -Wall -Wextra \
    src/rdprobe.c src/rdprobe_usb.c -framework CoreFoundation -o payload/setup/rdprobe
codesign --force --sign - --timestamp=none --generate-entitlement-der \
    --entitlements src/rdprobe.ents.plist payload/setup/rdprobe
codesign --verify --strict payload/setup/rdprobe
echo "Signed read-only probe: payload/setup/rdprobe"
