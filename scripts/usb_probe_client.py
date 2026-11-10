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
BOOTROM_OR_RECOVERY_PIDS = frozenset({0x1227, 0x1280, 0x1281, 0x1282, 0x1283})


def apple_usb_pids():
    """Passive Apple USB enumeration. No handshake, control transfer, or writes."""
    try:
        import usb.core
        devices = usb.core.find(find_all=True, idVendor=0x05ac)
        return tuple(sorted({d.idProduct for d in devices}))
    except Exception as exc:
        print(f'Apple USB enumeration unavailable: {type(exc).__name__}: {exc}', flush=True)
        return None


def final_usb_diagnostics():
    """Read-only cross-check when usbmuxd/iproxy cannot reach the probe."""
    pids = apple_usb_pids()
    if pids is not None:
        print('Apple USB products:', ', '.join(f'0x{x:04x}' for x in pids) if pids else '(none)',
              flush=True)
    try:
        r = subprocess.run(['irecovery', '-q'], capture_output=True, text=True, timeout=10)
        fields = ('MODE:', 'CPID:', 'PRODUCT:', 'MODEL:', 'PWND:')
        details = [line.strip() for line in r.stdout.splitlines() if line.strip().startswith(fields)]
        print(f"irecovery read-only status: exit={r.returncode}; "
              f"{', '.join(details) if details else r.stderr.strip()[-200:] or '(no details)'}", flush=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f'irecovery status unavailable: {exc}', flush=True)


def usbmux_ids():
    r = subprocess.run(['idevice_id', '-l'], capture_output=True, text=True, check=False)
    return r.stdout.split() if r.returncode == 0 else []


def valid_banner(data):
    return data.startswith(BANNER) and b"read_only=yes\n" in data


def observe_stock_usb(timeout):
    """Check whether *any* post-boot USB enumeration returns for the stock control.

    Never mistake a Recovery/DFU PID for a running ramdisk. Another connected
    Apple peripheral could be counted here: this is only an observation.
    """
    end = time.monotonic() + timeout
    previous_pids = object()
    previous_ids = object()
    print('STOCK restore-ramdisk baseline: observing Apple USB (NO restore request or writes)...', flush=True)
    while time.monotonic() < end:
        pids = apple_usb_pids()
        if pids != previous_pids:
            detail = ('unavailable' if pids is None else
                      ', '.join(f'0x{x:04x}' for x in pids) if pids else '(none)')
            print(f'Apple USB IDs: {detail}', flush=True)
            previous_pids = pids
        ids = usbmux_ids()
        if ids != previous_ids:
            print('usbmuxd IDs:', ', '.join(ids) if ids else '(none)', flush=True)
            previous_ids = ids
        if ids or (pids and any(pid not in BOOTROM_OR_RECOVERY_PIDS for pid in pids)):
            print('OBSERVED: a non-DFU/Recovery Apple USB device or usbmuxd ID returned.')
            print('This does NOT establish ramdisk startup or authorize installation.')
            final_usb_diagnostics()
            return 0
        time.sleep(1)
    print('NO NON-RECOVERY USB RETURN for the stock restore-ramdisk baseline.', file=sys.stderr)
    final_usb_diagnostics()
    return 1


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
    p.add_argument('--observe-only', action='store_true',
                   help='stock ramdisk baseline: monitor Apple USB without opening an iproxy listener')
    a = p.parse_args()
    if not shutil.which('idevice_id') or (not a.observe_only and not shutil.which('iproxy')):
        p.error('iproxy and idevice_id must be installed (run ./setup.sh)')
    if not 1 <= a.port <= 65535 or a.timeout < 1:
        p.error('port must be 1..65535 and timeout must be positive')
    if a.observe_only:
        return observe_stock_usb(a.timeout)
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
    final_usb_diagnostics()
    return 1


if __name__ == '__main__':
    sys.exit(main())
