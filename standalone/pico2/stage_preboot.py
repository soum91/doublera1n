#!/usr/bin/env python3
"""Inspect or stage personalized doublera1n Pico NAND IMG4s via existing Mac SSH.

Default is read-only. --stage adds five files under a NEW isolated Preboot
namespace, verifies each by a complete read-back SHA256, and atomically renames
the completed directory. Never overwrites Apple files or an existing stage.

No NVRAM/OTA/APFS volume changes. Does NOT prove that iBoot can use these files.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FILES = ('kernel.img4', 'dt.img4', 'tc.img4', 'txm.img4', 'ramdisk.img4')
DIR_RE = re.compile(r'^/private/preboot/([0-9A-F]{96})/doublera1n-pico2/([0-9a-f]{20})$')

class StageError(Exception):
    pass


def checked_export(export):
    export = Path(export).expanduser().resolve(strict=True)
    if export.is_symlink():
        raise StageError('export directory must not be a symlink')
    info = json.loads((export / 'stage-map.json').read_text())
    if info.get('board') != 'd431ap' or info.get('build') != '24A446':
        raise StageError('wrong board/build; expected d431ap/24A446')
    dest = info.get('ios_staging_directory', '')
    m = DIR_RE.fullmatch(dest)
    if not m or info.get('selected_manifest_hash') != m.group(1):
        raise StageError('manifest hash / destination mismatch')
    if info.get('staging_namespace') != '/doublera1n-pico2/' + m.group(2):
        raise StageError('staging namespace mismatch')
    if info.get('target_preboot_directory') != dest[len('/private/preboot'):]:
        raise StageError('iBoot mount-relative destination mismatch')
    records = info.get('files')
    if not isinstance(records, dict) or set(records) != set(FILES):
        raise StageError('expected exactly five boot assets')
    for name in FILES:
        path = export / 'preboot-files' / name
        if path.is_symlink() or not path.is_file():
            raise StageError('missing regular image: ' + name)
        expect = records[name]
        if not isinstance(expect, dict) or not isinstance(expect.get('sha256'), str):
            raise StageError('invalid stage-map entry for ' + name)
        h = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        if path.stat().st_size != expect.get('bytes') or h.hexdigest() != expect['sha256']:
            raise StageError('local size/hash mismatch: ' + name)
    return export, info, dest, m.group(1)


def ssh(checkout, script, *, input_file=None, stream_hash=False):
    if stream_hash:
        p = subprocess.Popen(['./dualboot.py', 'ssh', script], cwd=checkout,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        h, total = hashlib.sha256(), 0
        while True:
            buf = p.stdout.read(1024 * 1024)
            if not buf:
                break
            h.update(buf); total += len(buf)
        err = p.stderr.read().decode('utf-8', errors='replace')
        rc = p.wait()
        if rc:
            raise StageError('SSH readback failed: ' + err.strip())
        return total, h.hexdigest()
    with input_file.open('rb') if input_file else open(os.devnull, 'rb') as stream:
        result = subprocess.run(['./dualboot.py', 'ssh', script], cwd=checkout,
                                stdin=stream if input_file else None,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        msg = result.stderr.decode('utf-8', errors='replace').strip()
        raise StageError(f'SSH failed (exit {result.returncode}): {msg[:600]}')
    return result.stdout.decode('utf-8', errors='replace')


def run(export, checkout, stage=False):
    export, info, dest, h = checked_export(export)
    checkout = Path(checkout).expanduser().resolve(strict=True)
    if not (checkout / 'dualboot.py').is_file():
        raise StageError('expected original working checkout containing dualboot.py')
    root = '/private/preboot/' + h
    parent = root + '/doublera1n-pico2'
    temp = parent + '/.' + dest.rsplit('/', 1)[-1] + '.incomplete'
    # All these strings come only from validated fixed-format fields.
    print('Local SHA256 verification: 5/5 PASS')
    status = ssh(checkout,
                 f"set -eu; test -d '{root}'; test ! -L '{root}'; "
                 f"test ! -e '{dest}'; test ! -L '{dest}'; "
                 f"test ! -e '{temp}'; test ! -L '{temp}'; "
                 "test -d /private/preboot; "
                 "mount | grep -F ' on /private/preboot ' | grep -v 'read-only' >/dev/null; "
                 f"ls -ld '{root}'; df -k /private/preboot")
    # BSD df -k reports 1K blocks; refuse staging without generous reserve.
    lines = [line for line in status.splitlines() if '/private/preboot' in line]
    if not lines:
        raise StageError('cannot read remote Preboot free-space report')
    fields = lines[-1].split()
    try:
        available = int(fields[3]) * 1024
    except (IndexError, ValueError) as error:
        raise StageError('cannot parse Preboot free space; refusing write') from error
    required = sum(info['files'][name]['bytes'] for name in FILES) + 256 * 1024 * 1024
    if available < required:
        raise StageError('Preboot free space is insufficient with 256 MiB safety reserve')
    print('Phone Preboot and new destination validated (read-only):\n' + status)
    print(f'New destination: {dest}')
    print('No stock Apple files, active marker, APFS roles, or NVRAM will be altered.')
    if not stage:
        print('\nDRY RUN ONLY: no phone writes. Run with --stage to stage and hash-verify.')
        return
    print('Staging selected: a NEW directory will be created on the phone.')
    ssh(checkout,
        f"set -eu; test -d '{root}'; test ! -L '{root}'; "
        f"test ! -e '{dest}'; test ! -e '{temp}'; "
        f"if test -e '{parent}'; then test -d '{parent}' && test ! -L '{parent}'; "
        f"else mkdir -m 755 '{parent}'; fi; "
        f"mkdir -m 755 '{temp}'")
    try:
        for name in FILES:
            local = export / 'preboot-files' / name
            remote = temp + '/' + name
            ssh(checkout, f"set -eu; test ! -e '{remote}'; umask 022; cat > '{remote}'; chmod 644 '{remote}'", input_file=local)
            size, digest = ssh(checkout, f"cat '{remote}'", stream_hash=True)
            expected = info['files'][name]
            if size != expected['bytes'] or digest != expected['sha256']:
                raise StageError(f'read-back SHA256 mismatch for {name}; partial directory retained for manual inspection')
            print(f'ON-PHONE VERIFIED: {name} ({size} bytes)')
        ssh(checkout, f"set -eu; test -d '{temp}'; test ! -e '{dest}'; mv '{temp}' '{dest}'; sync")
        print('STAGED SUCCESSFULLY; five files at new isolated destination.')
        print('Note: iBoot reading those files and a successful jailbreak boot remain unverified.')
    except Exception:
        print(f'INCOMPLETE STAGING: temporary folder retained at {temp}; do not reboot until reviewed.', file=sys.stderr)
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--export', type=Path, default=Path.home() / 'Desktop/PicoNAND')
    p.add_argument('--checkout', type=Path, default=Path.home() / 'doublera1n-usb-537622e')
    p.add_argument('--stage', action='store_true', help='explicitly authorize one-time isolated Preboot writes')
    a = p.parse_args()
    try:
        run(a.export, a.checkout, a.stage)
    except (StageError, OSError, ValueError, json.JSONDecodeError) as e:
        print('STOP: ' + str(e), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
