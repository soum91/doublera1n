#!/usr/bin/env python3
"""Read-only doublera1n osbjb boot-artifact exporter and bundle verifier.

The .bin is a device-specific data container for a future Pico 2 + microSD
boot transport; it is NOT firmware and cannot boot an iPhone by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import zlib

MAGIC = b'DBPICO01'
VERSION = 1
HEADER = struct.Struct('<8sII16s16sQ')  # magic, version, count, board, build, total size
ENTRY = struct.Struct('<32s16sQQII32s') # name, action, offset, size, wait_ms, crc32, sha256
ALIGN = 512
BLOCK = 1024 * 1024
BOARD = 'd431ap'
BUILD = '24A446'
MAX_IMAGE = 1024 * 1024 * 1024  # fail on nonsensical or corrupt source

# Mirror lib/boot_chain.py --osbjb (not the old read-only probe).
# A single uploaded firmware image is followed by its iBoot command.
FULL = (
    ('iBSS.raw', 'dfu_boot', 0),
    ('iBEC.img4', 'ibec', 0),
    ('', 'go', 4000),
    ('ANE.img4', 'firmware', 0),
    ('AOP.img4', 'firmware', 0),
    ('AVE.img4', 'firmware', 1000),
    ('SPTM.img4', 'firmware', 3000),
    ('TXM.img4', 'firmware', 0),
    ('GFX.img4', 'firmware', 0),
    ('ISP.img4', 'firmware', 1000),
    ('PMP.img4', 'firmware', 0),
    ('RestoreTrustCache.img4', 'firmware', 0),
    ('SIO.img4', 'firmware', 0),
    ('WCH.img4', 'firmware', 0), # optional by device manifest
    ('RestoreRamdisk.img4', 'ramdisk', 2000),
    ('DeviceTree.img4', 'devicetree', 0),
    ('SEP.img4', 'rsepfirmware', 0),
    ('Kernelcache.img4', 'kernel', 0),
    ('', 'bootx', 0),
)


class BundleError(ValueError):
    pass


def _fixed(s: str, size: int) -> bytes:
    raw = s.encode('ascii')
    if not raw or len(raw) >= size or b'\0' in raw:
        raise BundleError(f'invalid metadata field: {s!r}')
    return raw.ljust(size, b'\0')


def _clean(b: bytes) -> str:
    try:
        return b.split(b'\0', 1)[0].decode('ascii')
    except UnicodeDecodeError as e:
        raise BundleError('non-ASCII entry name') from e


def _rounded(n: int) -> int:
    return (n + ALIGN - 1) // ALIGN * ALIGN


def _plan(stage_dir: Path):
    stages = []
    for name, action, delay in FULL:
        if name == 'WCH.img4' and not (stage_dir / name).exists():
            continue
        src = stage_dir / name if name else None
        if src:
            if src.is_symlink() or not src.is_file():
                raise BundleError(f'missing regular stage file: {src}')
            n = src.stat().st_size
            if n <= 0 or n > MAX_IMAGE:
                raise BundleError(f'invalid file size {n}: {src}')
        else:
            n = 0
        stages.append({'name': name, 'action': action, 'delay_ms': delay, 'size': n, 'path': src})
    return stages


def _validate_workspace(ws: Path, board: str, build: str):
    if not re.fullmatch(r'[a-z]\d+[a-z]{2}', board):
        raise BundleError('invalid board syntax')
    if not re.fullmatch(r'[A-Za-z0-9]+', build):
        raise BundleError('invalid build syntax')
    st = ws / 'state.json'
    if not st.is_file():
        raise BundleError(f'missing {st}')
    state = json.loads(st.read_text())
    if not state.get('installed'):
        raise BundleError('workspace does not identify an installed second Data volume')
    if state.get('board', '').lower() != board or state.get('build') != build:
        raise BundleError('workspace board/build mismatch; refusing potentially incorrect boot files')
    stage_dir = ws / 'build' / 'osbjb'
    if not stage_dir.is_dir():
        raise BundleError(f'jailbreak boot files missing: {stage_dir}')
    if not (ws / 'out' / 'apticket.installed.der').is_file():
        raise BundleError('installed APTicket absent; cannot establish personalized boot artifacts')
    stages = _plan(stage_dir)
    return stages


def _auto_workspace(root: Path, board: str, build: str) -> Path:
    candidates = []
    for st in root.glob(f'*-{build}/state.json'):
        try:
            j = json.loads(st.read_text())
            if j.get('installed') and j.get('build') == build and j.get('board', '').lower() == board:
                candidates.append(st.parent)
        except (OSError, ValueError, TypeError):
            continue
    if len(candidates) != 1:
        raise BundleError(f'expected exactly one installed {board}/{build} workspace in {root}, found {len(candidates)}; use --workspace')
    return candidates[0]


def prepare(args):
    board, build = args.board.lower(), args.build
    ws = Path(args.workspace).expanduser() if args.workspace else _auto_workspace(Path(args.work_root).expanduser(), board, build)
    stages = _validate_workspace(ws, board, build)
    return ws, stages


def describe(stages):
    for ix, st in enumerate(stages):
        print(f"{ix:2d} {st['action']:15s} {st['name'] or '(command only)':27s} {st['size']:>11,d} bytes  +{st['delay_ms']}ms")
    print(f"Boot image bytes: {sum(s['size'] for s in stages):,}")
    print('No firmware was sent, no phone modified.')


def _digest(path: Path):
    h, crc = hashlib.sha256(), 0
    with path.open('rb') as f:
        while buf := f.read(BLOCK):
            h.update(buf)
            crc = zlib.crc32(buf, crc)
    return h.digest(), crc & 0xffffffff


def export_bundle(args):
    ws, stages = prepare(args)
    describe(stages)
    if args.dry_run:
        return
    dst = Path(args.output).expanduser().resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not args.overwrite:
        raise BundleError(f'{dst} already exists (use --overwrite for explicit replacement)')
    start = _rounded(HEADER.size + len(stages) * ENTRY.size)
    cursor = start
    desc = []
    for st in stages:
        path = st['path']
        sha, crc = _digest(path) if path else (bytes(32), 0)
        desc.append((st, cursor if path else 0, sha, crc))
        if path:
            cursor = _rounded(cursor + st['size'])
    fd, tmp = tempfile.mkstemp(prefix='.bootplan-', suffix='.tmp', dir=str(dst.parent))
    try:
        with os.fdopen(fd, 'w+b') as out:
            out.write(HEADER.pack(MAGIC, VERSION, len(desc), _fixed(args.board.lower(), 16), _fixed(args.build, 16), cursor))
            for st, offset, sha, crc in desc:
                out.write(ENTRY.pack(st['name'].encode().ljust(32, b'\0'), _fixed(st['action'], 16),
                                     offset, st['size'], st['delay_ms'], crc, sha))
            for st, offset, sha, crc in desc:
                if not st['path']:
                    continue
                out.seek(offset)
                with st['path'].open('rb') as source:
                    while buf := source.read(BLOCK):
                        out.write(buf)
            out.truncate(cursor)
            out.flush()
            os.fsync(out.fileno())
        # Only publish a fully written, cross-checked image.
        inspect(Path(tmp), quiet=True)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print(f'Prepared personalized microSD boot data: {dst} ({cursor:,} bytes)')
    print('DATA ONLY: this is not a UF2 or a working standalone device booter yet.')


def inspect(path: Path, quiet=False):
    total = path.stat().st_size
    with path.open('rb') as f:
        raw = f.read(HEADER.size)
        if len(raw) != HEADER.size:
            raise BundleError('truncated bundle header')
        magic, ver, count, board_raw, build_raw, declared_size = HEADER.unpack(raw)
        if magic != MAGIC or ver != VERSION or count > 64 or count == 0:
            raise BundleError('wrong magic, version or entry count')
        board, build = _clean(board_raw), _clean(build_raw)
        if total != declared_size:
            raise BundleError('bundle length does not match header')
        if _rounded(HEADER.size + count * ENTRY.size) > total:
            raise BundleError('truncated entry table')
        entries, used = [], []
        for _ in range(count):
            raw = f.read(ENTRY.size)
            if len(raw) != ENTRY.size:
                raise BundleError('truncated entry')
            name_raw, action_raw, offset, size, delay, crc, sha = ENTRY.unpack(raw)
            name, action = _clean(name_raw), _clean(action_raw)
            if (not name and (offset or size or crc or sha != bytes(32))) or (name and (not size or offset % ALIGN or offset + size > total)):
                raise BundleError(f'invalid stage extent: {name!r}')
            if name:
                for off, n in used:
                    if offset < off + n and off < offset + size:
                        raise BundleError('overlapping stage extents')
                used.append((offset, size))
            entries.append((name, action, offset, size, delay, crc, sha))
        actions = [(n, a) for n, a, *_ in entries]
        expected = [(n, a) for n, a, _ in FULL if n != 'WCH.img4' or ('WCH.img4', 'firmware') in actions]
        if actions != expected:
            raise BundleError('action order is not the current OS B jailbreak boot chain')
        for name, _, offset, size, _, crc, sha in entries:
            if not name:
                continue
            f.seek(offset)
            remaining, got_crc, got_sha = size, 0, hashlib.sha256()
            while remaining:
                buf = f.read(min(remaining, BLOCK))
                if not buf:
                    raise BundleError('truncated image')
                remaining -= len(buf)
                got_crc = zlib.crc32(buf, got_crc)
                got_sha.update(buf)
            if got_crc & 0xffffffff != crc or got_sha.digest() != sha:
                raise BundleError(f'corrupt or modified image: {name}')
    if not quiet:
        print(f'Verified {count} boot stages; board={board}, build={build}, bytes={total:,}; CRC32 + SHA256 OK')
    return entries


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('export', help='build read-only personalized BOOT.BIN for microSD')
    e.add_argument('--work-root', default='~/dualboot-work')
    e.add_argument('--workspace')
    e.add_argument('--board', default=BOARD)
    e.add_argument('--build', default=BUILD)
    e.add_argument('--output', required=True)
    e.add_argument('--overwrite', action='store_true')
    e.add_argument('--dry-run', action='store_true')
    i = sub.add_parser('inspect', help='verify BOOT.BIN format and every stage checksum')
    i.add_argument('bundle')
    args = p.parse_args(argv)
    try:
        if args.cmd == 'export':
            export_bundle(args)
        else:
            inspect(Path(args.bundle))
    except (BundleError, OSError, ValueError) as ex:
        p.exit(2, f'ERROR: {ex}\n')


if __name__ == '__main__':
    main()
