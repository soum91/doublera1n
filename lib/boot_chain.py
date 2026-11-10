#!/usr/bin/env python3
"""Boot chain for the dual-boot setup ramdisk and OS B, sent to a device in pwned DFU.
usbliter8ctl boot iBSS.raw -> iBEC.img4 + go -> firmware... -> ramdisk -> devicetree -> rsepfirmware
-> kernel -> bootx.  Unlike `irecovery -c`, every command is sent with a control transfer whose STALL
(= iBoot rejected the command) is detected; the chain stops before bootx on any failure."""
import os, re, subprocess, sys, time
import usb.core
import usb.util

HERE = os.path.dirname(os.path.abspath(__file__))
JB = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import osbcfg
OSBJB = '--osbjb' in sys.argv   # OS B + jailbreak ramdisk (jbinit as PID 1, jb=md0)
OSB = '--osb' in sys.argv or OSBJB
RESUME = '--resume' in sys.argv   # OS B normal boot instead of the setup ramdisk
C = osbcfg.work('osbjb' if OSBJB else 'osb' if OSB else 'chain')
CTL = os.environ.get('USBLITER8CTL') or os.path.join(JB, 'tools/usbliter8ctl')
FIRMWARE = [('ANE.img4', 0), ('AOP.img4', 0), ('AVE.img4', 1), ('SPTM.img4', 3), ('TXM.img4', 0),
            ('GFX.img4', 0), ('ISP.img4', 1), ('PMP.img4', 0), ('StaticTrustCache.img4', 0),
            ('RestoreTrustCache.img4', 0), ('SIO.img4', 0), ('WCH.img4', 0)]
OPTIONAL = {'WCH.img4'}             # wireless-charging firmware: iPads have none
# iOS 27's SPTM/TXM and both trust caches are kept in the controlled minimal
# experiment; only peripheral firmwares are omitted. Never use for installation.
PROBE_CORE_FIRMWARE = frozenset({'SPTM.img4', 'TXM.img4',
                                 'StaticTrustCache.img4', 'RestoreTrustCache.img4'})
RECOVERY_PIDS = (0x1280, 0x1281, 0x1282, 0x1283)  # libirecovery's Recovery A/B/C/D
if OSB: FIRMWARE = [f for f in FIRMWARE if f[0] != 'StaticTrustCache.img4']   # System TC sent as rtsc (mk_osb.py)

def recovery_devices():
    """Enumerate all documented Apple Recovery USB IDs, not just 0x1281."""
    for pid in RECOVERY_PIDS:
        d = usb.core.find(idVendor=0x05ac, idProduct=pid)
        if d is not None:
            yield d

def device_diagnostics():
    """Read-only mode details; never send another image on an ambiguous USB state."""
    try:
        devices = usb.core.find(find_all=True, idVendor=0x05ac)
        for d in devices:
            if d.idProduct not in (0x1227, *RECOVERY_PIDS):
                continue
            try:
                serial = d.serial_number or ''
                cpid = re.search(r'CPID:([0-9A-Fa-f]+)', serial)
                print(f"   Apple USB PID=0x{d.idProduct:04x} CPID={cpid.group(1) if cpid else 'unavailable'}", flush=True)
            except (ValueError, usb.core.USBError) as e:
                print(f"   Apple USB PID=0x{d.idProduct:04x} (serial unavailable: {e})", flush=True)
            finally:
                usb.util.dispose_resources(d)
    except (ValueError, usb.core.USBError) as e:
        print(f"   USB enumeration error: {e}", flush=True)
    try:
        q = subprocess.run(['irecovery', '-q'], capture_output=True, text=True, timeout=10)
        interesting = ('MODE:', 'CPID:', 'PRODUCT:', 'MODEL:', 'PWND:')
        details = [line.strip() for line in q.stdout.splitlines() if line.strip().startswith(interesting)]
        print(f"   irecovery -q exit={q.returncode}: {', '.join(details) or (q.stderr.strip()[-250:] or 'no mode details')}", flush=True)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"   irecovery -q unavailable: {e}", flush=True)

def recovery(timeout=90):
    """a Recovery device whose string descriptors answer (a half-torn-down one after `go` does not)"""
    end = time.time() + timeout
    while time.time() < end:
        for d in recovery_devices():
            try:
                if 'CPID:8030' in (d.serial_number or ''): return d
            except (ValueError, usb.core.USBError):
                pass
            usb.util.dispose_resources(d)
        time.sleep(0.5)
    print(f"!! no (healthy) Recovery device after {timeout}s; current USB state:", flush=True)
    device_diagnostics()
    sys.exit("!! no (healthy) Recovery device")

def gone(timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        detected = list(recovery_devices())
        for d in detected: usb.util.dispose_resources(d)
        if not detected: return True
        time.sleep(0.3)
    return False

def apple_usb_pids():
    """Read-only USB enumeration, including normal/restore device IDs."""
    try:
        devices = usb.core.find(find_all=True, idVendor=0x05ac)
        result = sorted({d.idProduct for d in devices})
        return tuple(result)
    except (ValueError, usb.core.USBError):
        return None

def observe_boot_usb(seconds=12, interval=0.5):
    """Record re-enumeration after bootx without assuming a kernel ever started."""
    end = time.monotonic() + seconds
    last = object()
    while time.monotonic() < end:
        pids = apple_usb_pids()
        if pids != last:
            detail = ('enumeration unavailable' if pids is None else
                      ', '.join(f'0x{pid:04x}' for pid in pids) if pids else 'no Apple USB device')
            print(f"   post-bootx USB: {detail}", flush=True)
            last = pids
        time.sleep(interval)
    return last

def upload(name):
    for attempt in range(4):              # libirecovery sometimes can't open the device right after a command
        r = subprocess.run(['irecovery', '-f', os.path.join(C, name)], capture_output=True, text=True)
        if not r.returncode: return
        print(f"   upload {name} attempt {attempt + 1} failed: {r.stderr.strip()[-120:]} - retrying", flush=True)
        time.sleep(2); usb.util.dispose_resources(recovery(30))
    sys.exit(f"!! upload {name} failed: {r.stderr.strip()[-200:]}")

def cmd(c, may_disconnect=False):
    dev = recovery()
    try:
        dev.ctrl_transfer(0x40, 0, 0, 0, c.encode() + b'\0', 30000)
        print(f"   {c:20s} ok", flush=True)
    except usb.core.USBError as e:
        if may_disconnect:
            print(f"   {c:20s} (USB gone: {e}) - expected", flush=True); return
        sys.exit(f"!! '{c}' rejected by iBoot ({e}) - stopping before bootx")
    finally:
        usb.util.dispose_resources(dev)

def send(name, c, pause=0):
    print(f" - {name}", flush=True)
    upload(name); cmd(c)
    if pause: time.sleep(pause)

def main():
    if '--probe-minimal-fw' in sys.argv:
        if OSB or OSBJB:
            sys.exit('!! minimal firmware is forbidden for 2nd Data/jailbreak boots')
        global FIRMWARE
        FIRMWARE = [entry for entry in FIRMWARE if entry[0] in PROBE_CORE_FIRMWARE]
        print('[probe] experimental minimal-firmware boot: SPTM, TXM, static/restore trust caches only',
              flush=True)
    out = subprocess.run(['irecovery', '-q'], capture_output=True, text=True).stdout
    if RESUME:                           # iBEC already up (an earlier run died after [2]): continue from firmware
        if 'NONC:' not in out or 'PWND' in out: sys.exit("--resume needs the device sitting in iBEC")
        print("[resume] iBEC already up - skipping [1]/[2]", flush=True)
        return stages_from_firmware()
    if 'PWND: usbliter8' not in out: sys.exit("device not in pwned DFU")
    print("[1] iBSS (raw)", flush=True)
    # Use the same venv as dualboot.py: the Mac's global `python3` may lack PyUSB.
    # Never suppress the sender's failure then misreport it as a Recovery timeout.
    ibss = subprocess.run([sys.executable, CTL, 'boot', os.path.join(C, 'iBSS.raw')],
                          capture_output=True, text=True)
    if ibss.returncode:
        print(f"!! iBSS sender exited {ibss.returncode}", flush=True)
        for stream in (ibss.stdout, ibss.stderr):
            if stream.strip(): print(stream.strip()[-2500:], flush=True)
        device_diagnostics()
        sys.exit("!! iBSS send failed; stopping before iBEC or any filesystem operations")
    print(f"   iBSS sender exited 0; {ibss.stdout.strip()[-120:] or 'no sender output'}", flush=True)
    usb.util.dispose_resources(recovery()); time.sleep(3)
    print("[2] iBEC + go", flush=True)
    upload('iBEC.img4')
    # `irecovery -c go` (libirecovery ignores the status-stage timeout of the
    # hand-off), then leave the device alone for 2 s instead of polling it while iBSS tears USB down
    subprocess.run(['irecovery', '-c', 'go'], capture_output=True, text=True)
    time.sleep(2)
    print(f"   iBSS left USB: {gone()}", flush=True)
    recovery(60); time.sleep(2)
    print("   iBEC is up", flush=True)
    # bring the display up in iBEC so the kernel gets a framebuffer and -v is visible
    d = recovery()
    try:
        d.ctrl_transfer(0x40, 0, 0, 0, b'bgcolor 0 0 0\0', 30000); print("   bgcolor 0 0 0      ok", flush=True)
    except usb.core.USBError as e:
        print(f"   bgcolor rejected ({e}) - continuing", flush=True)
    finally:
        usb.util.dispose_resources(d)    # release the handle, or irecovery -f can't open the device
    stages_from_firmware()

def stages_from_firmware():
    print("[3] firmware", flush=True)
    for name, pause in FIRMWARE:
        if name in OPTIONAL and not os.path.exists(os.path.join(C, name)):
            print(f" - {name} (not on this board)", flush=True); continue
        send(name, 'firmware', pause)
    if OSB and not OSBJB:
        time.sleep(2)
    else:
        print("[4] ramdisk", flush=True)
        send('RestoreRamdisk.img4', 'ramdisk', 2)
    print("[5] devicetree, SEP, kernel", flush=True)
    send('DeviceTree.img4', 'devicetree')
    send('SEP.img4', 'rsepfirmware')
    print(" - Kernelcache.img4", flush=True); upload('Kernelcache.img4')
    print("[6] bootx", flush=True)
    usb.util.dispose_resources(recovery(10))
    result = subprocess.run(['irecovery', '-c', 'bootx'], capture_output=True, text=True)
    # Some successful USB handoffs disconnect before the CLI can read a reply;
    # report the exit code but do not equate it with boot success/failure.
    print(f"   bootx command exit={result.returncode}; "
          f"stdout={result.stdout.strip()[-300:] or '(empty)'}; "
          f"stderr={result.stderr.strip()[-300:] or '(empty)'}", flush=True)
    observe_boot_usb()
    for d in recovery_devices():
        try:
            back = 'CPID:8030' in (d.serial_number or '')
        except (ValueError, usb.core.USBError):
            back = False
        usb.util.dispose_resources(d)
        if back: sys.exit("!! bootx returned to the Recovery prompt - iBoot rejected the boot (see UART hash lines)")
    print("[+] bootx command issued; kernel and ramdisk startup NOT verified - " +
          ("watch UART for 2nd Data boot" if OSB else "test the read-only USB listener / watch UART"), flush=True)

if __name__ == '__main__':
    main()
