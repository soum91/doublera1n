#!/usr/bin/env bash
# Build only the read-only USB transport probe, leaving existing rdsetup untouched.
set -euo pipefail
cd "$(dirname "$0")/.."
sdk=$(xcrun --sdk iphoneos --show-sdk-path)
mkdir -p payload/setup
xcrun clang -target arm64-apple-ios17.0 -isysroot "$sdk" -O2 -Wall -Wextra \
    src/rdprobe.c -o payload/setup/rdprobe
ldid -Ssrc/rdsetup.ents.plist payload/setup/rdprobe
echo "Signed read-only probe: payload/setup/rdprobe"
