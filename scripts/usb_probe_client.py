#!/usr/bin/env python3
"""Host-side read-only detector for the optional doublera1n restore-ramdisk TCP probe.

It uses iproxy/usbmuxd; it cannot communicate with an iPhone still in DFU.
Only use after explicitly booting the read-only probe ramdisk. No device writes.
"""
import argparse
import shutil
import socket
import subprocess
import sys
import time

PORT = 27047
BANNER = b"DOUBLERA1N_USB_PROBE_V1\n"


def usbmux_ids():
    r = subprocess.run(['idevice_id', '-l'], capture_output=True, text=True, check=False)
    return r.stdout.split() if r.returncode == 0 else []


def valid_banner(data):
    return data.startswith(BANNER) and b"read_only=yes\n" in data


def try_proxy(udid, port):
    argv = ['iproxy', str(port), str(port)]
    if udid:
        argv.extend(['-u', udid])
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        # Give iproxy a moment to open its listening socket. It may exit if
        # usbmuxd has no restore-mode device; do not assume success.
        for _ in range(8):
            if proc.poll() is not None:
                return None
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.5) as conn:
                    conn.settimeout(2)
                    return conn.recv(512)
            except (ConnectionError, OSError, socket.timeout):
                time.sleep(0.25)
        return None
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--timeout', type=int, default=120, help='seconds to wait after probe ramdisk boot')
    p.add_argument('--udid', help='device identifier for iproxy, if auto-detection is ambiguous')
    p.add_argument('--port', type=int, default=PORT)
    a = p.parse_args()
    if not shutil.which('iproxy') or not shutil.which('idevice_id'):
        p.error('iproxy and idevice_id must be installed (run ./setup.sh)')
    if not 1 <= a.port <= 65535 or a.timeout < 1:
        p.error('port must be 1..65535 and timeout must be positive')
    end = time.monotonic() + a.timeout
    last_ids = None
    print('Looking for the read-only restore-ramdisk USB probe (no writes)...', flush=True)
    while time.monotonic() < end:
        ids = usbmux_ids()
        if ids != last_ids:
            print('usbmuxd IDs:', ', '.join(ids) if ids else '(none)', flush=True)
            last_ids = ids
        if a.udid:
            choices = [a.udid]
        elif ids:
            choices = ids
        else:
            # Some usbmuxd versions don't list restore devices through idevice_id;
            # try a single-device iproxy without a UDID as a fallback.
            choices = [None]
        for device in choices:
            reply = try_proxy(device, a.port)
            if reply and valid_banner(reply):
                print('SUCCESS: Mac reached the read-only USB probe inside the restore ramdisk.')
                print(reply.decode('ascii', 'replace').strip())
                return 0
        time.sleep(2)
    print('NO USB PROBE RESPONSE. This does not prove the restore USB stack is unavailable; '
          'do not attempt the real installer without a verified return transport.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
