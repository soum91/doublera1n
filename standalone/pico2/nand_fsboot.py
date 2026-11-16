#!/usr/bin/env python3
"""Prepare an *offline* Pico-sized iBoot filesystem-boot probe.

This is an experimental first-stage only.  It neither boots DataB nor installs
anything on the iPhone.  It intentionally does not create a UF2.  In particular,
fsboot loading a STOCK kernel from NAND is not a rootless jailbreak bootstrap.

The aim is to reuse the repository's existing iBoot command-table patch to
measure whether an ordinary Recovery/pwned-DFU iBoot can initiate NAND fsboot
without any USB kernel/ramdisk upload.  Real iOS 27.0.1 behavior is unverified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / 'lib' / 'patch_iboot.py'
BOARD = 'd431ap'
BUILD = '24A446'
DEFAULT_ARGS = '-v serial=3 debug=0x2014e'
# Independently extracted from the d431ap/24A446 Apple IPSW; see BINARY_FINDINGS.md.
STOCK_SHA256 = '9f8d8c31484800b5dad37dbbc4953d8b4a9c969d46e7b53f82414a607e143f48'
REQUIRED_PATCH_LOG = (
    'memboot->fsboot',
    'remote-boot -> local',
    'auto-boot -> false',
    'boot-args',
)


class ProbeError(RuntimeError):
    pass


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def source_audit(root: Path = ROOT) -> dict:
    """Read the actual source: no claims about physical iBoot capabilities."""
    patcher = (root / 'lib/patch_iboot.py').read_text()
    builder = (root / 'lib/mk_osbjb.py').read_text()
    boot = (root / 'lib/boot_chain.py').read_text()
    setup = (root / 'src/rdsetup.c').read_text()
    checks = {
        'fsboot_command_swap_available': 'def patch_fsboot_cmd(' in patcher,
        'fsboot_swap_disabled_in_existing_jailbreak_build': bool(re.search(r"patch_iboot\.py'\),\s*'--no-fsboot'", builder)),
        'jailbreak_ramdisk_built_separately': 'def build_ramdisk():' in builder and "sign(IM4P(fourcc='rdsk', payload=rd)" in builder,
        'existing_boot_sends_ramdisk': "send('RestoreRamdisk.img4', 'ramdisk'" in boot,
        'existing_boot_sends_patched_kernel': "upload('Kernelcache.img4')" in boot,
        'existing_installer_mounts_preboot_read_only': 'mount_apfs", "-o", "ro", predev' in setup,
        'existing_installer_uses_dataB_for_setup_data': '"/mnt2/jb"' in setup,
    }
    return {
        'board': BOARD, 'build': BUILD,
        'source_checks': checks,
        'safe_to_conclude_nand_boots_jailbreak': False,
        'requires_on_device_verification_of_patched_fsboot': True,
        'does_not_check_whats_on_the_phone': True,
        'remaining_research': [
            'Does patched iBoot enter NAND fsboot on d431ap/24A446 from the pwned-DFU launch path?',
            'Can it obtain required SPTM/TXM, DeviceTree, trust caches, and modified kernel from on-device storage?',
            'Can the 96 MiB jbinit ramdisk be read from an already accessible boot volume, or eliminated safely?',
            'Could an alternate ramdisk handoff preserve stock Preboot and permit recovery after a failed boot?',
        ],
    }


def check_source(root: Path = ROOT) -> dict:
    audit = source_audit(root)
    if not all(audit['source_checks'].values()):
        broken = [k for k, v in audit['source_checks'].items() if not v]
        raise ProbeError('source layout changed; review manually: ' + ', '.join(broken))
    return audit


def prepare(raw_iboot: Path, output: Path, patcher: Path = PATCHER,
            runner=subprocess.run, root: Path = ROOT) -> dict:
    check_source(root)
    if not raw_iboot.is_file() or raw_iboot.is_symlink():
        raise ProbeError('provide an existing *decrypted stock iBEC* raw file (no img4 wrapper)')
    raw_size = raw_iboot.stat().st_size
    if raw_size < 1024 or raw_size > 16 * 1024 * 1024:
        raise ProbeError('unexpected raw iBEC size')
    with raw_iboot.open('rb') as f:
        f.seek(0x300)
        marker = f.read(0x20)
    if b'mBoot-' not in marker and b'iBoot-' not in marker:
        raise ProbeError('not raw iBoot: missing expected version marker at 0x300')
    if sha256_file(raw_iboot) != STOCK_SHA256:
        raise ProbeError('stock iBEC SHA256 mismatch: not verified d431ap/24A446 bytes')
    output = output.resolve()
    if output == raw_iboot.resolve():
        raise ProbeError('output cannot overwrite source iBoot')
    if output == patcher.resolve():
        raise ProbeError('invalid output')
    try:
        output.relative_to(root.resolve())
    except ValueError:
        pass
    else:
        raise ProbeError('do not write a personalized iBoot into the Git repository')
    if output.exists():
        raise ProbeError('output already exists: refusing overwrite')
    if not patcher.is_file():
        raise ProbeError('repository iBoot patcher missing')
    # Keep all changes to a temporary file until the source patcher reports all
    # required transformations.  No NVRAM, APFS, DFU, or USB operations here.
    with tempfile.TemporaryDirectory(prefix='nand-fsboot-') as tmp:
        candidate = Path(tmp) / 'nand-fsboot.raw'
        cmd = [sys.executable, str(patcher), '--local', '--no-autoboot',
               '--keep-cmds', '--boot-args=' + DEFAULT_ARGS,
               str(raw_iboot), str(candidate)]
        result = runner(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ProbeError('patch_iboot failed: ' + (result.stderr or result.stdout)[-1300:])
        missing = [tag for tag in REQUIRED_PATCH_LOG if tag not in result.stdout]
        if missing:
            raise ProbeError('required iBoot transformations not confirmed: ' + ', '.join(missing))
        if not candidate.is_file() or candidate.stat().st_size != raw_size:
            raise ProbeError('patched iBoot missing or size changed')
        if sha256_file(candidate) == sha256_file(raw_iboot):
            raise ProbeError('patcher produced unchanged bytes')
        # Pico 2 4 MiB is shared by firmware and payload; the exact available
        # space depends on the FINAL firmware layout, not a hard-coded guess.
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(candidate.read_bytes())
    return {
        'status': 'OFFLINE_PROOF_OF_CONCEPT_ONLY',
        'target_board': BOARD, 'target_build': BUILD,
        'source_sha256': sha256_file(raw_iboot),
        'candidate_sha256': sha256_file(output),
        'candidate_bytes': output.stat().st_size,
        'output': str(output),
        'console_command_to_exercise_fsboot': 'memboot',
        'expected_if_it_works': 'attempt stock NAND filesystem boot, NOT doublera1n/DataB',
        'does_not_include': ['patched OS B kernel', 'TXM/SPTM boot patches',
                             'DeviceTree edits', 'trust cache', 'jbinit ramdisk'],
        'device_tested': False,
        'uf2_generated': False,
        'requires_phone_flash_or_filesystem_write': False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('audit', help='read-only analysis of current repository boot dependencies')
    build = sub.add_parser('prepare', help='offline raw iBEC -> patched NAND-fsboot first-stage candidate')
    build.add_argument('--stock-ibec-raw', required=True, type=Path)
    build.add_argument('--output', required=True, type=Path)
    a = p.parse_args(argv)
    try:
        out = check_source() if a.cmd == 'audit' else prepare(a.stock_ibec_raw, a.output)
    except (ProbeError, OSError, subprocess.TimeoutExpired) as e:
        print('NAND FSBoot probe: ' + str(e), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
