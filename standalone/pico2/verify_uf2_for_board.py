#!/usr/bin/env python3
"""Read-only UF2 flash extent preflight for explicitly named RP235x boards.

This checks file framing, payload ranges and the declared board flash capacity.
It does NOT identify the physical board, inspect its wiring, or flash hardware.
Do not treat a PASS as approval to attach an iPhone or as an on-device boot test.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import struct
import sys

UF2_MAGIC0 = 0x0A324655
UF2_MAGIC1 = 0x9E5D5157
UF2_END = 0x0AB16F30
FAMILY_ID_PRESENT = 0x2000
FLASH_BASE = 0x10000000
CAPACITY = {
    "pico2": 4 * 1024 * 1024,    # Genuine Raspberry Pi Pico 2, 4 MiB external flash
    "rp2354a": 2 * 1024 * 1024, # RP2354A integrated flash; additional flash NOT presumed
}


class PreflightError(ValueError):
    pass


def inspect_uf2(path: Path) -> dict:
    data = path.read_bytes()
    if not data or len(data) % 512:
        raise PreflightError("not a nonempty 512-byte-block UF2")
    entries = []
    for offset in range(0, len(data), 512):
        block = data[offset:offset + 512]
        m0, m1, flags, address, length, number, total, family = struct.unpack_from("<8I", block)
        if (m0, m1) != (UF2_MAGIC0, UF2_MAGIC1) or struct.unpack_from("<I", block, 508)[0] != UF2_END:
            raise PreflightError(f"invalid UF2 magic at file byte {offset}")
        if length != 256 or not (flags & FAMILY_ID_PRESENT):
            raise PreflightError(f"unexpected payload size or missing family flag at block {number}")
        entries.append((number, total, family, address, length))
    counts = Counter(family for _, _, family, _, _ in entries)
    dominant, count = counts.most_common(1)[0]
    globally_numbered = all(total == len(entries) for _, total, _, _, _ in entries)
    if globally_numbered:
        if sorted(n for n, _, _, _, _ in entries) != list(range(len(entries))):
            raise PreflightError("missing or duplicate UF2 block number")
    else:
        # SDK 2.2.0's E10 absolute-family record uses its own count (2),
        # while the ARM secure image is numbered independently. Do not
        # miscount that record as ARM flash or accept arbitrary exceptions.
        main = [e for e in entries if e[2] == dominant]
        aux = [e for e in entries if e[2] != dominant]
        if (dominant != 0xe48bff59 or len(aux) != 1 or
                aux[0] != (0, 2, 0xe48bff57, 0x10ffff00, 256) or
                any(e[1] != count for e in main)):
            raise PreflightError("UF2 block-count field mismatch")
        if sorted(e[0] for e in main) != list(range(count)):
            raise PreflightError("missing or duplicate main-family UF2 block number")
    if count < 2:
        raise PreflightError("insufficient main flash blocks")
    # Pico SDK RP2350-E10 workaround may add isolated auxiliary-family blocks.
    if sum(n for family, n in counts.items() if family != dominant) > 2:
        raise PreflightError("unexpected second UF2 flash family")
    seen = set()
    end = FLASH_BASE
    for _, _, family, addr, size in entries:
        if family != dominant:
            continue
        if addr < FLASH_BASE or addr % 256:
            raise PreflightError("invalid or misaligned main flash address")
        if addr in seen:
            raise PreflightError("duplicate flash block address")
        seen.add(addr)
        end = max(end, addr + size)
    return {
        "uf2_bytes": len(data),
        "flash_extent_bytes": end - FLASH_BASE,
        "main_family": f"0x{dominant:08x}",
        "main_blocks": count,
        "auxiliary_blocks": len(entries) - count,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--board", choices=tuple(CAPACITY), required=True,
                   help="the actual, separately identified hardware; not guessed from the UF2")
    p.add_argument("--uf2", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        report = inspect_uf2(a.uf2.expanduser())
        capacity = CAPACITY[a.board]
        print(f"Target declared: {a.board}; flash capacity: {capacity:,} bytes")
        print(f"UF2 size: {report['uf2_bytes']:,} bytes (container size != flash usage)")
        print(f"Flash extent: {report['flash_extent_bytes']:,} bytes")
        print(f"Main family: {report['main_family']}; auxiliary blocks: {report['auxiliary_blocks']}")
        if report["flash_extent_bytes"] > capacity:
            print(f"STOP: exceeds {a.board} flash by {report['flash_extent_bytes'] - capacity:,} bytes.")
            return 2
        print("Flash extent fits the DECLARED target, but wiring, chip identification,")
        print("bootloader support, flashing safety and actual iPhone boot are UNVERIFIED.")
        return 0
    except (PreflightError, OSError, struct.error) as e:
        print(f"STOP: UF2 validation failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
