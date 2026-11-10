#!/usr/bin/env python3
"""Read-only triage of iPhone boot/panic reports after an experimental boot.

`collect` asks libimobiledevice to COPY (not remove) existing crash logs from
an unlocked, trusted iPhone booted into stock iOS. It never requests restore,
DFU, installation, or an iOS update. `analyze` also accepts manually exported
Analytics logs. No logs are uploaded, and report contents are not printed.

An early iBoot/SEP/kernel failure can happen before iOS can persist a panic
report. An empty result therefore cannot establish that the boot was healthy.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

REPORT_PREFIXES = ('panic-full', 'panic-base', 'panic.', 'resetcounter')
REPORT_SUFFIXES = ('.ips', '.panic', '.plist', '.crash', '.txt')
CLUES = (
    ('SPTM/TXM', re.compile(r'\b(?:sptm|txm|trustedexecutionmonitor|securepagetablemonitor)\b', re.I)),
    ('SEP', re.compile(r'\b(?:sep|sepos|sepfirmware|sepfw|sks)\b', re.I)),
    ('Trust cache / signing', re.compile(r'\b(?:trust.?cache|amfi|codesign|code.?signing|cs_invalid_page)\b', re.I)),
    ('RAM disk / APFS', re.compile(r'\b(?:ramdisk|rd=md0|root.?device|apfs|mountroot)\b', re.I)),
    ('Graphics / IOSurface', re.compile(r'\b(?:iosurface|iogpu|agx|displaycoprocessor)\b', re.I)),
    ('Watchdog / userspace', re.compile(r'\b(?:watchdog|launchd|userspace|userspace watchdog)\b', re.I)),
)


def eligible(path):
    name = path.name.lower()
    return path.is_file() and name.startswith(REPORT_PREFIXES) and (
        name.endswith(REPORT_SUFFIXES) or '.ips.' in name)


def find_reports(root):
    # Limit walking to a bounded directory tree. The crashreport tool copies
    # files under the caller's requested directory, not the entire computer.
    return sorted((p for p in root.rglob('*') if eligible(p)),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def describe(path):
    # Raw reports may contain user/device identifiers. Report only the file
    # name, modification time, and the presence of diagnostic clue families.
    content = path.read_bytes()[:2_000_000].decode('utf-8', errors='replace')
    matched = [name for name, pattern in CLUES if pattern.search(content)]
    timestamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return timestamp.strftime('%Y-%m-%d %H:%M UTC'), matched


def analyze(directory, limit):
    reports = find_reports(directory)
    if not reports:
        print('No panic/reset reports found. Early boot failures can leave NO stored crash report.')
        print('This result does not prove the kernel, SEP, or ramdisk started.')
        return 0
    print(f'Found {len(reports)} local panic/reset report(s); showing up to {limit} newest:')
    for path in reports[:limit]:
        timestamp, matched = describe(path)
        print(f'  {timestamp}  {path.name}')
        print('    Clue families: ' + (', '.join(matched) if matched else 'none recognized'))
    print('These are keyword clues, NOT a verified cause. Compare timestamps to the actual test.')
    print('Original reports remain local and unchanged; inspect one before diagnosing a specific failure.')
    return 0


def connected_device(udid):
    if not shutil.which('idevice_id'):
        raise RuntimeError('idevice_id is unavailable (install libimobiledevice on the Mac)')
    result = subprocess.run(['idevice_id', '-l'], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError('Cannot list trusted iPhones: ' + result.stderr.strip()[-150:])
    devices = result.stdout.split()
    if udid:
        if udid not in devices:
            raise RuntimeError('The requested phone is not listed as a connected trusted device')
        return udid
    if len(devices) != 1:
        raise RuntimeError(f'Expected one connected trusted iPhone, found {len(devices)}. '
                           'Disconnect other devices or supply --udid.')
    return devices[0]


def collect(directory, udid):
    if not shutil.which('idevicecrashreport'):
        raise RuntimeError('idevicecrashreport is unavailable (install libimobiledevice on the Mac)')
    chosen = connected_device(udid)
    directory.mkdir(parents=True, exist_ok=True)
    # -k/--keep is CRITICAL: the default command may remove reports on the
    # device after copying. Never omit it. No '-r' (remove) or restore calls.
    command = ['idevicecrashreport', '--keep', '-u', chosen, str(directory)]
    print('Copying existing reports WITHOUT deleting them from the iPhone...')
    result = subprocess.run(command, capture_output=True, text=True, timeout=240)
    if result.returncode:
        raise RuntimeError('Crash report copy failed (device logs were not cleared). '
                           + (result.stderr or result.stdout).strip()[-250:])
    print(f'Crash reports copied locally into: {directory}')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    col = sub.add_parser('collect', help='copy phone crash reports without removing any')
    col.add_argument('--output', type=Path, help='existing or new local directory; default uses a unique temp directory')
    col.add_argument('--udid', help='explicit trusted device ID if multiple iPhones are connected')
    col.add_argument('--limit', type=int, default=8, help='maximum report summaries to show')
    scan = sub.add_parser('analyze', help='analyze local reports, never connect to the phone')
    scan.add_argument('directory', type=Path)
    scan.add_argument('--limit', type=int, default=8)
    args = parser.parse_args(argv)
    if args.limit < 1 or args.limit > 100:
        parser.error('--limit must be in 1..100')
    try:
        if args.command == 'collect':
            root = args.output or Path(tempfile.mkdtemp(prefix='doublera1n-panic-'))
            collect(root, args.udid)
        else:
            root = args.directory
            if not root.is_dir():
                raise RuntimeError(f'Not a directory: {root}')
        return analyze(root, args.limit)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
