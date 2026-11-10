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
import zipfile

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


def eligible(name):
    name = Path(name).name.lower()
    return name.startswith(REPORT_PREFIXES) and (
        name.endswith(REPORT_SUFFIXES) or '.ips.' in name)


def find_reports(root):
    """Load a folder or a ZIP export; never unpack potentially untrusted paths."""
    if root.is_file() and zipfile.is_zipfile(root):
        with zipfile.ZipFile(root) as archive:
            for entry in archive.infolist():
                if eligible(entry.filename) and entry.file_size <= 2_000_000:
                    with archive.open(entry) as stream:
                        yield Path(entry.filename).name, stream.read(2_000_000).decode('utf-8', errors='replace')
    elif root.is_dir():
        for path in root.rglob('*'):
            if path.is_file() and eligible(path.name):
                with path.open('rb') as stream:
                    yield path.name, stream.read(2_000_000).decode('utf-8', errors='replace')


def report_time(content):
    # File metadata belongs to the COPY, not the original event. ResetCounter
    # reports in particular can all have identical copy/ZIP mtimes.
    stamp = re.search(r'(?m)^Date:\s*(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)? [+-]\d{4})', content)
    if not stamp:
        stamp = re.search(r'"timestamp"\s*:\s*"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)? [+-]\d{4})"', content)
    if not stamp:
        return None
    value = stamp.group(1)
    fmt = '%Y-%m-%d %H:%M:%S.%f %z' if '.' in value else '%Y-%m-%d %H:%M:%S %z'
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def report_field(content, name):
    match = re.search(r'(?m)^' + re.escape(name) + r':\s*([^\r\n]+)', content)
    return match.group(1).strip() if match else None


def describe(name, content):
    # Never dump original report contents; they can contain IDs and secrets.
    stamp = report_time(content)
    display_time = stamp.strftime('%Y-%m-%d %H:%M:%S %z') if stamp else 'time unavailable'
    if name.lower().startswith('resetcounter'):
        count = report_field(content, 'Boot failure count') or '?'
        stage = report_field(content, 'Boot stage') or '?'
        faults = report_field(content, 'Boot faults') or '?'
        return stamp, display_time, f'Boot failure count={count}; boot stage={stage}; faults={faults}'
    matched = [label for label, pattern in CLUES if pattern.search(content)]
    return stamp, display_time, ('Panic clue families: ' + (', '.join(matched) if matched else 'none recognized'))


def analyze(directory, limit):
    reports = [(name, *describe(name, content)) for name, content in find_reports(directory)]
    if not reports:
        print('No panic/reset reports found. Early boot failures can leave NO stored crash report.')
        print('This result does not prove the kernel, SEP, or ramdisk started.')
        return 0
    reports.sort(key=lambda report: report[1] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    print(f'Found {len(reports)} local panic/reset report(s); showing up to {limit} newest:')
    if not any(name.lower().startswith('panic') for name, *_ in reports):
        print('  No panic-full/panic-base reports in this collection; ResetCounter is not a kernel backtrace.')
    for name, _date, display_time, summary in reports[:limit]:
        print(f'  {display_time}  {name}')
        print('    ' + summary)
    print('Boot stage codes are reported verbatim; their meanings are not independently verified.')
    print('Clues are not a verified cause. Compare report dates to the actual boot attempts.')
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
    scan = sub.add_parser('analyze', help='analyze a folder or ZIP of reports, never connect to the phone')
    scan.add_argument('directory', type=Path, help='directory or ZIP of previously exported reports')
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
            if not root.is_dir() and not (root.is_file() and zipfile.is_zipfile(root)):
                raise RuntimeError(f'Not a directory or ZIP archive: {root}')
        return analyze(root, args.limit)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
