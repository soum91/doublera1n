#!/usr/bin/env python3
"""Prepare a private, host-only NAND boot candidate from an installed workspace.

Nothing here connects to or writes to an iPhone. No UF2 is generated. The output
requires separate staging review and physical validation before it can be used.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import iboot_audit

BOARD, BUILD = iboot_audit.BOARD, iboot_audit.BUILD
BOOTARGS = 'jb=md0 -v serial=3 debug=0x2014e launchd_unsecure_cache=1 wdt=-1'
# source osbjb asset, source FourCC, NAND FourCC, name, volatile environment key
ASSETS = (
    ('Kernelcache.img4', 'rkrn', 'krnl', 'kernel.img4', 'boot-path'),
    ('DeviceTree.img4', 'rdtr', 'dtre', 'dt.img4', 'dt-path'),
    ('RestoreTrustCache.img4', 'rtsc', 'trst', 'tc.img4', 'tc-path'),
    ('TXM.img4', 'trxm', 'trxm', 'txm.img4', 'txm-path'),
    ('RestoreRamdisk.img4', 'rdsk', 'rdsk', 'ramdisk.img4', 'boot-ramdisk'),
)
SETENV = 0xa9cec
FSBOOT = 0xb28
MEMBOOT = 0x154c
MEMBOOT_BYTES = 748
CHAR_DESCRIPTOR = 0x11b2d8

class BootError(ValueError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build_wrapper(base: int, origin: int, capacity: int, overrides: list[tuple[str, str]], patcher):
    """Small ARM64 console handler: set ONLY RAM env values, then tail-call fsboot.

    No external assembler, borrowed hook source, persistent NVRAM API or KPF code
    is needed. The old memboot body is no longer used. Preserve PAC/SP/frame
    conventions; return -1 without calling fsboot if any setter returns nonzero.
    """
    if [key for key, _ in overrides] != [a[4] for a in ASSETS]:
        raise BootError('unexpected environment override keys or order')
    for key, value in overrides:
        if not value.startswith('/doublera1n-pico2/') or not value.isascii() or '\0' in value:
            raise BootError('override must point into the dedicated Preboot staging namespace')
        if len(value) > 100 or '..' in Path(value).parts:
            raise BootError('invalid staging path')
    words = []
    branches = []
    addresses = []
    def emit(word):
        words.append(word)
    def addr(reg, name):
        addresses.append((len(words), reg, name))
        emit(0); emit(0)
    # PACIBSP; SUB SP,SP,#32; STP X29,X30,[SP,#16]; ADD X29,SP,#16
    for word in (0xd503237f, 0xd10083ff, 0xa9017bfd, 0x910043fd): emit(word)
    for index, (key, value) in enumerate(overrides):
        addr(0, f'k{index}')
        emit(0xaa0003e1)  # mov x1,x0
        emit(patcher.enc_add_imm(2, 0, len(key) + 1))
        addr(3, 'char')
        addr(4, f'v{index}')
        emit(0xaa0403e5)  # mov x5,x4
        emit(patcher.enc_add_imm(6, 4, len(value) + 1))
        emit(0xaa0303e7)  # mov x7,x3
        emit(0xb90003ff)  # str wzr,[sp]: flags=0, same RAM setter as defaults
        pc = origin + len(words) * 4
        emit(0x94000000 | (((SETENV - pc) // 4) & 0x3ffffff))
        branches.append(len(words)); emit(0)  # cbnz w0, fail
    for word in (0xa9417bfd, 0x910083ff, 0xd50323ff): emit(word)  # ldp; add sp; autibsp
    pc = origin + len(words) * 4
    emit(0x14000000 | (((FSBOOT - pc) // 4) & 0x3ffffff))
    failure = origin + len(words) * 4
    for word in (0x12800000, 0xa9417bfd, 0x910083ff, 0xd65f0fff): emit(word)
    labels = {'char': CHAR_DESCRIPTOR}
    strings = bytearray()
    code_size = len(words) * 4
    for index, (key, value) in enumerate(overrides):
        for name, text in ((f'k{index}', key), (f'v{index}', value)):
            labels[name] = origin + code_size + len(strings)
            strings.extend(text.encode('ascii') + b'\0')
    for index, reg, name in addresses:
        target = base + labels[name]
        pc = base + origin + index * 4
        words[index] = patcher.enc_adrp(reg, pc, target)
        words[index + 1] = patcher.enc_add_imm(reg, reg, target & 0xfff)
    for index in branches:
        delta = (failure - (origin + index * 4)) // 4
        words[index] = 0x35000000 | ((delta & 0x7ffff) << 5)  # CBNZ W0
    output = bytearray(struct.pack('<' + 'I' * len(words), *words) + strings)
    output.extend(bytes((-len(output)) % 4))
    guard_at = origin + len(output)
    guard = [0xd503237f, 0xa9bf7bfd, 0x910003fd]
    pc = guard_at + len(guard) * 4
    guard.append(0x94000000 | (((0xc1a2c - pc) // 4) & 0x3ffffff))
    guard.append(0)  # cbnz w0, failure
    # iBoot's file loader clears these globals on image failure but returns 0.
    # Require both the loaded ramdisk address and size before allowing fsboot
    # to proceed to a jb=md0 kernel. Do not change the loader predicate.
    for reg, table in ((8, 0x1ea058), (9, 0x1ea060)):
        pc = base + guard_at + len(guard) * 4
        guard.append(patcher.enc_adrp(reg, pc, base + table))
        guard.append(0xf9400000 | ((((base + table) & 0xfff) // 8) << 10) | (reg << 5) | reg)
        guard.append(0xf9400000 | (reg << 5) | reg)
        guard.append(0)  # cbz xreg, failure
    guard.append(0x52800000)  # mov w0,0
    guard.append(0x14000002)  # b epilogue
    failure_index = len(guard)
    guard.append(0x12800000)
    guard.extend((0xa8c17bfd, 0xd65f0fff))
    for index, reg, nonzero in ((4, 0, True), (8, 8, False), (12, 9, False)):
        delta = failure_index - index
        guard[index] = (0x35000000 if nonzero else 0xb4000000) | (delta << 5) | reg
    output.extend(struct.pack('<' + 'I' * len(guard), *guard))
    if len(output) > capacity:

        raise BootError(f'wrapper needs {len(output)} bytes; verified cave holds {capacity}')
    return bytes(output), {'ramdisk_guard_offset': guard_at, 'wrapper_bytes': len(output), 'code_bytes': code_size,
                    'failure_offset': failure, 'string_offsets': labels}


def prepare_candidate(raw: bytes, overrides, runner=subprocess.run):
    iboot_audit.validate_raw(raw)
    resolved = iboot_audit.resolve_preconditions(raw)
    if not resolved['ramdisk_loader_enabled'] or resolved['default_apfs_role'] != 16:
        raise BootError('verified RAM ramdisk/preboot preconditions do not hold')
    with tempfile.TemporaryDirectory(prefix='nand-first-stage-') as temp:
        source = Path(temp) / 'stock.raw'; patched = Path(temp) / 'candidate.raw'
        source.write_bytes(raw)
        result = runner([sys.executable, str(ROOT / 'lib/patch_iboot.py'),
                         '--local', '--no-autoboot', '--keep-cmds',
                         '--boot-args=' + BOOTARGS, str(source), str(patched)],
                        capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise BootError('iBoot preparation failed: ' + (result.stderr or result.stdout)[-1000:])
        for marker in ('memboot->fsboot', 'remote-boot -> local', 'auto-boot -> false', 'boot-args'):
            if marker not in result.stdout:
                raise BootError('required patch missing: ' + marker)
        data = bytearray(patched.read_bytes())
    patcher = iboot_audit.patcher_module()
    patcher.BASE, end = patcher._layout.set_layout(raw)
    if len(data) != len(raw) or patcher._layout.handler_size(raw, MEMBOOT) != MEMBOOT_BYTES:
        raise BootError('verified image or cave size changed')
    # Source proof: no direct control-flow references enter the command's body
    # from other code. The exact-image binding also rules out another layout.
    for pc in range(0, end, 4):
        branch = iboot_audit.direct_branch(patcher.u32(raw, pc), pc)
        if branch and MEMBOOT <= branch['target_offset'] < MEMBOOT + MEMBOOT_BYTES and not MEMBOOT <= pc < MEMBOOT + MEMBOOT_BYTES:
            raise BootError('memboot body has an external direct branch')
    wrapper, layout = build_wrapper(patcher.BASE, MEMBOOT, MEMBOOT_BYTES, overrides, patcher)
    data[MEMBOOT:MEMBOOT + MEMBOOT_BYTES] = wrapper.ljust(MEMBOOT_BYTES, b'\0')
    entries = patcher.find_cmd_entry(raw, 'memboot', 0x100000, len(raw) - 0x40)
    entries = [e for e in entries if patcher.u64(raw, e + 0x20) >> 63 and
               patcher.u64(raw, e + 0x20) & 0xffffffff == MEMBOOT]
    if len(entries) != 1:
        raise BootError('memboot command table no longer matches')
    guard_pc = 0x1ab8
    guard_delta = (layout['ramdisk_guard_offset'] - guard_pc) // 4
    struct.pack_into('<I', data, guard_pc, 0x94000000 | (guard_delta & 0x3ffffff))
    # Restore the original authenticated command slot target, now our wrapper.
    # The original slot key/diversity/chain bits remain untouched.
    data[entries[0] + 0x20:entries[0] + 0x28] = raw[entries[0] + 0x20:entries[0] + 0x28]
    return bytes(data), {'status': 'DEVICE_UNTESTED_NAND_BOOT_CANDIDATE',
                         'board': BOARD, 'build': BUILD, 'raw_bytes': len(data),
                         'candidate_sha256': sha(data), 'candidate_crc32': zlib.crc32(data), 'command': 'memboot',
                         'flash_layout': {'firmware_limit': 0x100000, 'image_header_bytes': 0x100,
                                          'flash_bytes': 4*1024*1024,
                                          'used_end_offset': 0x100100 + len(data),
                                          'remaining_bytes': 4*1024*1024 - 0x100100 - len(data)},
                         'persistent_nvram_api_used': False, 'device_tested': False,
                         'uf2_generated': False, 'resolved_preconditions': resolved,
                         **layout}


def raw_payload(image):
    from pyimg4 import IM4P
    copy = IM4P(image.output())
    if copy.payload.encrypted:
        raise BootError('encrypted source payload')
    if copy.payload.compression.value != 0:
        copy.payload.decompress()
    return copy.payload.output().data


def verify_patched_assets(workspace: Path, images: dict, profile_dir: Path | None = None):
    """Recreate kernel, TXM and DT bytes from build-matched stock firmware."""
    from pyimg4 import IM4P
    import plistlib
    patcher = iboot_audit.patcher_module()
    kpf = patcher._layout
    firmware = (workspace / 'build/ipsw').resolve()
    manifest = plistlib.loads((firmware / 'BuildManifest.plist').read_bytes())
    component = iboot_audit.manifest_component(manifest)
    # Ensure the manifest-matched iBEC is also the pinned stock source.
    iboot_audit.firmware_raw(firmware)
    identity = next(i for i in manifest['BuildIdentities'] if i['Info'].get('DeviceClass') == BOARD
                    and i['Info'].get('RestoreBehavior') == 'Erase')
    def stock(key):
        entry = identity['Manifest'][key]
        path = (firmware / entry['Info']['Path']).resolve()
        if not path.is_relative_to(firmware): raise BootError('stock path escapes firmware tree')
        data = path.read_bytes()
        if hashlib.sha384(data).digest() != entry['Digest']: raise BootError('stock component digest mismatch')
        return raw_payload(IM4P(data))
    profile = (profile_dir or ROOT / 'profiles' / f'{BOARD}-{BUILD}').expanduser().resolve()
    if not profile.is_dir():
        raise BootError('successful installation profile missing; pass --profile-dir pointing to its original profiles/d431ap-24A446 directory')
    for filename, key, records, excluded in (
        ('Kernelcache.img4', 'KernelCache', ('kernel-boot-jit.json', 'kernel-ramdisk.json', 'kernel-osb.json'), ('kernel.identity',)),
        ('TXM.img4', 'Ap,TrustedExecutionMonitor', ('txm-boot-permissive.json',), ())):
        original = stock(key)
        recs = kpf.load_records([str(profile / n) for n in records], exclude_prefixes=excluded)
        expected = bytearray(original)
        for offset, _old, new in kpf.records_to_words(original, recs):
            struct.pack_into('<I', expected, offset, new)
        if raw_payload(images[filename].im4p) != bytes(expected):
            raise BootError(f'{filename} differs from the selected installation profile; select the profile used by the successful installation')
    with tempfile.TemporaryDirectory(prefix='nand-dt-check-') as temp:
        src, dst = Path(temp) / 'stock', Path(temp) / 'expected'
        src.write_bytes(stock('DeviceTree'))
        spec = importlib.util.spec_from_file_location('nand_dt_patch', ROOT / 'lib/dt_patch.py')
        dt = importlib.util.module_from_spec(spec); spec.loader.exec_module(dt)
        result = subprocess.run([sys.executable, str(ROOT / 'lib/dt_patch.py'), str(src), str(dst)] + dt.OSB_OPS,
                                capture_output=True, text=True, timeout=30)
        if result.returncode or raw_payload(images['DeviceTree.img4'].im4p) != dst.read_bytes():
            raise BootError('DeviceTree differs from the exact DataB patch plan')
    ramdisk = raw_payload(images['RestoreRamdisk.img4'].im4p)
    if len(ramdisk) != 96 * 1024 * 1024 or ramdisk[0x20:0x24] != b'NXSB':
        raise BootError('expected the existing 96 MiB APFS jbinit ramdisk')
    cache = raw_payload(images['RestoreTrustCache.img4'].im4p)
    if len(cache) < 24 or struct.unpack_from('<I', cache)[0] != 2 or len(cache) != 24 + 24 * struct.unpack_from('<I', cache, 20)[0]:
        raise BootError('invalid v2 combined trust cache')


def export_workspace(workspace: Path, stock_raw: Path | None, output: Path, profile_dir: Path | None = None):
    from pyimg4 import IMG4, IM4M
    workspace = workspace.expanduser().resolve()
    output = output.expanduser().resolve()
    if output.exists() or output.is_relative_to(workspace) or output.is_relative_to(ROOT):
        raise BootError('output must be a new private directory outside the repository and source workspace')
    state = json.loads((workspace / 'state.json').read_text())
    if state.get('installed') is not True or state.get('board') != BOARD or state.get('build') != BUILD:
        raise BootError('expected an already-installed d431ap/24A446 workspace')
    ticket_bytes = (workspace / 'out/apticket.installed.der').read_bytes()
    ticket = IM4M(ticket_bytes)
    if ticket.chip_id != 0x8030 or ticket.board_id != 2 or not 0 < ticket.ecid < 2**64:
        raise BootError('installed ticket hardware identity mismatch')
    canonical_ticket = ticket.output()
    if canonical_ticket != ticket_bytes:
        raise BootError('installed ticket encoding changed; cannot bind the existing Preboot hash directory')
    manifest_hash = hashlib.sha384(canonical_ticket).hexdigest().upper()
    stage = workspace / 'build/osbjb'
    images, retagged, files = {}, {}, {}
    for filename, source_type, target_type, name, key in ASSETS:
        src = stage / filename
        if src.is_symlink() or not src.is_file(): raise BootError('missing regular source asset: ' + filename)
        image = IMG4(src.read_bytes())
        if image.im4p.fourcc != source_type or image.im4m.output() != canonical_ticket:
            raise BootError('source image type or installed ticket mismatch: ' + filename)
        if image.im4r is not None:
            raise BootError('unexpected restore properties in source: ' + filename)
        images[filename] = image
        before = image.im4p.payload.output().data
        image.im4p.fourcc = target_type
        data = image.output()
        checked = IMG4(data)
        if checked.im4m.output() != canonical_ticket or checked.im4p.payload.output().data != before:
            raise BootError('retag altered payload or installed ticket')
        retagged[name] = data
        files[name] = {'bytes': len(data), 'sha256': sha(data), 'fourcc': target_type, 'environment_key': key}
    verify_patched_assets(workspace, images, profile_dir)
    identity = sha(json.dumps({'board': BOARD, 'build': BUILD, 'ticket_sha256': sha(canonical_ticket),
                              'files': files}, sort_keys=True).encode())[:20]
    namespace = '/doublera1n-pico2/' + identity
    overrides = [(key, namespace + '/' + name) for _, _, _, name, key in ASSETS]
    raw = stock_raw.read_bytes() if stock_raw else iboot_audit.firmware_raw(workspace / 'build/ipsw')
    candidate, report = prepare_candidate(raw, overrides)
    # Construct everything in a sibling temporary directory; publish only on
    # complete validation. No existing directory, phone or source is modified.
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.nand-export-', dir=output.parent))
    try:
        folder = temp / 'preboot-files'; folder.mkdir()
        for name, data in retagged.items(): (folder / name).write_bytes(data)
        (temp / 'nand-first-stage.raw').write_bytes(candidate)
        (temp / 'nand_device_config.h').write_text(
            '#pragma once\n#include <stdint.h>\n'
            + '#define DBNAND_EXPECTED_ECID UINT64_C(0x' + f'{ticket.ecid:016x}' + ')\n')
        report.update({'private_device_material': True, 'ticket_ecid_hex': f'{ticket.ecid:016x}',
                       'staging_namespace': namespace, 'selected_manifest_hash': manifest_hash,
                       'target_preboot_directory': '/' + manifest_hash + namespace,
                       'ios_staging_directory': '/private/preboot/' + manifest_hash + namespace,
                       'preboot_prefix_requires_device_confirmation': True,
                       'files': files, 'volatile_overrides': dict(overrides),
                       'unchanged_internal_dependencies': ['SPTM', 'SEP and SEP patches', 'peripheral firmware',
                                                           'roothash/System snapshot and cryptex boot objects'],
                       'phone_staging_performed': False, 'requires_separate_staging_review': True})
        (temp / 'stage-map.json').write_text(json.dumps(report, indent=2) + '\n')
        temp.rename(output)
    finally:
        if temp.exists(): shutil.rmtree(temp)
    return {'status': report['status'], 'output': str(output), 'assets': len(files),
            'first_stage_bytes': len(candidate), 'phone_modified': False, 'uf2_generated': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export', help='private local image preparation; no phone writes')
    export.add_argument('--workspace', type=Path)
    export.add_argument('--profile-dir', type=Path, help='original successful installation profile directory')
    export.add_argument('--work-root', type=Path, default=Path(os.environ.get('DUALBOOT_HOME') or ROOT / 'dualboot-work').expanduser())
    export.add_argument('--stock-ibec-raw', type=Path, help='optional; normally extracted from the installed workspace firmware')
    export.add_argument('--output', type=Path, required=True)
    check = sub.add_parser('selfcheck', help='prepare in memory and report layout; no boot image saved')
    source = check.add_mutually_exclusive_group(required=True)
    source.add_argument('--firmware-dir', type=Path)
    source.add_argument('--apple-download', action='store_true')
    args = p.parse_args(argv)
    try:
        if args.command == 'selfcheck':
            raw = iboot_audit.apple_raw() if args.apple_download else iboot_audit.firmware_raw(args.firmware_dir)
            overrides = [(a[4], '/doublera1n-pico2/selfcheck/' + a[3]) for a in ASSETS]
            _candidate, report = prepare_candidate(raw, overrides)
            report['private_assets_present'] = False
            print(json.dumps(report, indent=2))
        else:
            workspace = args.workspace
            if workspace is None:
                from boot_bundle import _auto_workspace, BundleError
                try:
                    workspace = _auto_workspace(args.work_root.expanduser(), BOARD, BUILD)
                except BundleError as error:
                    raise BootError(str(error)) from error
            print(json.dumps(export_workspace(workspace, args.stock_ibec_raw, args.output, args.profile_dir), indent=2))
    except (BootError, iboot_audit.AuditError, OSError, ValueError, KeyError, ImportError) as e:
        print('NAND boot preparation: ' + str(e), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
