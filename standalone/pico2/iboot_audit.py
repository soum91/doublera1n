#!/usr/bin/env python3
"""Read-only, exact-image iBoot inspection for d431ap / 24A446.

Reports binary references, not proof that NAND/filesystem boot works on a phone.
No USB, ticket, device connection, or firmware patching occurs here.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
BOARD, BUILD = 'd431ap', '24A446'
STOCK_SHA256 = '9f8d8c31484800b5dad37dbbc4953d8b4a9c969d46e7b53f82414a607e143f48'
STOCK_SIZE = 2842448
APPLE_URL = ('https://updates.cdn-apple.com/2026FallFCS/585d6bab-0662-42a6-ac0f-1e0392ab92ef/'
             'iPhone12,3,iPhone12,5_27.0.1_24A446_Restore.ipsw')
ANCHORS = ('boot-ramdisk', '/boot/ramdisk', '/boot/kernelcache', 'ramdisk-size',
           '/System/Library/Caches/com.apple.kernelcaches/kernelcache',
           'mount upgrade partition', 'load upgrade iBEC')

class AuditError(ValueError):
    pass


def validate_raw(raw: bytes):
    if len(raw) != STOCK_SIZE or hashlib.sha256(raw).hexdigest() != STOCK_SHA256:
        raise AuditError('raw image is not the verified stock d431ap/24A446 iBEC; refusing another build or modified bytes')


def manifest_component(manifest: dict) -> dict:
    if manifest.get('ProductBuildVersion') != BUILD:
        raise AuditError('BuildManifest build mismatch')
    identities = [i for i in manifest['BuildIdentities']
                  if i['Info'].get('DeviceClass') == BOARD and
                  i['Info'].get('RestoreBehavior') == 'Erase']
    if len(identities) != 1:
        raise AuditError('expected one d431ap Erase identity')
    identity = identities[0]
    if int(str(identity['ApChipID']), 0) != 0x8030 or int(str(identity['ApBoardID']), 0) != 2:
        raise AuditError('BuildManifest chip/board ID mismatch')
    component = identity['Manifest']['iBEC']
    path = Path(component['Info']['Path'])
    if path.is_absolute() or '..' in path.parts:
        raise AuditError('component path escapes firmware directory')
    return component


def decode_component(component: dict, data: bytes) -> bytes:
    """Manifest consistency plus a separately pinned raw hash, not CMS verification."""
    digest = component.get('Digest')
    if not isinstance(digest, bytes) or len(digest) != 48 or hashlib.sha384(data).digest() != digest:
        raise AuditError('iBEC SHA384 differs from BuildManifest')
    from pyimg4 import IM4P
    image = IM4P(data)
    if image.fourcc != 'ibec' or image.payload.encrypted:
        raise AuditError('expected unencrypted stock iBEC IM4P')
    image.payload.decompress()
    raw = image.payload.output().data
    validate_raw(raw)
    return raw


def firmware_raw(directory: Path) -> bytes:
    root = directory.resolve()
    manifest = plistlib.loads((root / 'BuildManifest.plist').read_bytes())
    component = manifest_component(manifest)
    path = (root / component['Info']['Path']).resolve()
    if not path.is_relative_to(root):
        raise AuditError('component path escapes firmware directory')
    return decode_component(component, path.read_bytes())


def apple_raw() -> bytes:
    """HTTP range-read just manifest and iBEC; no ticket requests or disk writes."""
    from remotezip import RemoteZip
    with RemoteZip(APPLE_URL, timeout=60) as archive:
        if archive.getinfo('BuildManifest.plist').file_size > 2 * 1024 * 1024:
            raise AuditError('unexpectedly large BuildManifest')
        manifest = plistlib.loads(archive.read('BuildManifest.plist'))
        component = manifest_component(manifest)
        path = component['Info']['Path']
        if archive.getinfo(path).file_size > 16 * 1024 * 1024:
            raise AuditError('unexpectedly large iBEC')
        return decode_component(component, archive.read(path))


def patcher_module():
    lib = str(ROOT / 'lib')
    if lib not in sys.path:
        sys.path.insert(0, lib)
    spec = importlib.util.spec_from_file_location('iboot_audit_patcher', ROOT / 'lib/patch_iboot.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def direct_branch(word: int, offset: int):
    """Decode AArch64 immediate B/BL only; never infer indirect call targets."""
    if word & 0x7c000000 != 0x14000000:
        return None
    immediate = word & 0x3ffffff
    if immediate & 0x2000000:
        immediate -= 0x4000000
    return {'kind': 'bl' if word & 0x80000000 else 'b',
            'target_offset': offset + 4 * immediate}


def references(raw: bytes, end: int, targets: set[int], patcher):
    """One pass over code for adjacent ADRP+ADD references (no data scanning).

    Deliberately only adjacent pairs: avoids inventing register provenance across
    intervening instructions. Missing references are not proof of absence.
    """
    result = {t: [] for t in targets}
    for offset in range(0, end - 4, 4):
        adrp, add = struct.unpack_from('<II', raw, offset)
        if adrp & 0x9f000000 != 0x90000000:
            continue
        reg = adrp & 31
        if add & 0xffc00000 != 0x91000000 or add & 31 != reg or add >> 5 & 31 != reg:
            continue
        target = patcher.adrp_target(adrp, offset) + patcher.add_imm(add)
        if target in result:
            calls = []
            # A bounded listing of nearby branches, not a call graph or proof of
            # which function owns the string or which branch consumes it.
            for pc in range(offset + 8, min(end, offset + 48), 4):
                branch = direct_branch(struct.unpack_from('<I', raw, pc)[0], pc)
                if branch:
                    calls.append({'offset': pc, **branch})
            result[target].append({'adrp_offset': offset, 'add_offset': offset + 4,
                                   'nearby_direct_branches': calls})
    return result


def analyze(raw: bytes) -> dict:
    validate_raw(raw)
    patcher = patcher_module()
    patcher.BASE, code_end = patcher._layout.set_layout(raw)
    commands = {}
    for name in ('fsboot', 'memboot', 'ramdisk', 'bootx', 'go', 'upgrade'):
        entries = []
        for entry in patcher.find_cmd_entry(raw, name, 0x100000, len(raw) - 0x40):
            pointer = patcher.u64(raw, entry + 0x20)
            target = pointer & 0xffffffff
            if pointer >> 63 and target < code_end and target % 4 == 0:
                entries.append({'table_offset': entry, 'handler_offset': target})
        commands[name] = entries
    for name in ('fsboot', 'memboot'):
        if len(commands[name]) != 1:
            raise AuditError(f'expected one authenticated {name} command handler')
    strings = {s: patcher.find_all(raw, s.encode() + b'\0') for s in ANCHORS}
    refs = references(raw, code_end, {o for offsets in strings.values() for o in offsets}, patcher)
    # Edges confirmed in this exact pinned image. These expose a shared rdsk
    # candidate path and its gate, without assigning undocumented API semantics.
    edges = []
    for offset, meaning in ((0xc8c, 'fsboot calls shared setup helper'),
                            (0x1a74, 'boot-ramdisk lookup candidate'),
                            (0x1ab8, 'optional boot-ramdisk path calls shared rdsk helper'),
                            (0x6200, 'upgrade /boot/ramdisk path calls same rdsk helper'),
                            (0xc1a68, 'rdsk helper calls feature predicate'),
                            (0xc1b20, 'rdsk helper calls image-loader candidate')):
        branch = direct_branch(struct.unpack_from('<I', raw, offset)[0], offset)
        if not branch or branch['kind'] != 'bl':
            raise AuditError('recorded binary edge no longer matches verified image')
        edges.append({'offset': offset, 'observation': meaning, **branch})
    return {
        'board': BOARD, 'build': BUILD, 'status': 'STATIC_BINARY_EVIDENCE_ONLY',
        'raw_sha256': STOCK_SHA256, 'raw_bytes': len(raw),
        'first_stage_storage': {
            'raw_bytes': len(raw), 'deflate_bytes': len(zlib.compress(raw, 9)),
            'pico2_flash_bytes': 4 * 1024 * 1024,
            'raw_flash_remainder_before_pico_firmware': 4 * 1024 * 1024 - len(raw),
            'complete_boot_chain_measured': False,
            'decompressor_implemented': False,
        },
        'load_address': patcher.BASE, 'code_end_offset': code_end,
        'commands': commands, 'observed_direct_calls': edges,
        'anchors': {s: [{'string_offset': off, 'references': refs[off]} for off in offsets]
                    for s, offsets in strings.items()},
        'nand_read_proven': False, 'jailbreak_boot_proven': False,
        'interpretation': 'The /boot paths occur in upgrade code. fsboot also reaches a shared helper with an optional boot-ramdisk lookup and a feature-gated rdsk loader. Static references do not establish volume access, key semantics, or jailbreak startup.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--firmware-dir', type=Path, help='extracted BuildManifest and iBEC at its original path (requires pyimg4)')
    source.add_argument('--stock-ibec-raw', type=Path, help='exact SHA256-pinned decrypted stock image')
    source.add_argument('--apple-download', action='store_true', help='range-read the exact Apple IPSW manifest and iBEC (requires pyimg4 and remotezip)')
    args = parser.parse_args(argv)
    try:
        raw = (apple_raw() if args.apple_download else
               firmware_raw(args.firmware_dir) if args.firmware_dir else args.stock_ibec_raw.read_bytes())
        print(json.dumps(analyze(raw), indent=2))
    except (AuditError, OSError, KeyError, ValueError, ImportError) as error:
        print(f'iBoot audit: {error}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
