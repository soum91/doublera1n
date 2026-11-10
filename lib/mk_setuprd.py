#!/usr/bin/env python3
"""Setup ramdisk for the dualboot tool: Apple's restore ramdisk (RestoreRamDisk of the IPSW, unmodified except for
two files) whose restored_external is rdsetup, plus its trust cache with rdsetup's cdhash added.

  mk_setuprd.py install|remove|probe|stock -> $OSB_WORK/setuprd-<mode>.img4 (rdsk), $OSB_WORK/setuptc-<mode>.img4 (rtsc)

  /usr/local/bin/restored_external    = rdsetup (payload/setup/rdsetup, built from src/rdsetup.c)
  /usr/local/share/dualboot/mode      = "install" | "remove" | "probe"
The probe substitutes a separate read-only TCP listener binary for rdsetup.
The stock baseline leaves Apple's restore ramdisk and trust cache byte-for-byte intact
inside their re-signed IMG4 containers: no payload injection, disk mount, or setup program.
Both are signed with $OSB_OUT/apticket.im4m (our iBoot does not check AP image signatures anyway).
Nothing here touches the phone."""
import os, shutil, struct, subprocess, sys, tempfile
from pyimg4 import IM4P, IM4M, IMG4

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import osbcfg

ROOT = os.path.dirname(HERE)
RDSETUP = os.environ.get('OSB_RDSETUP') or os.path.join(ROOT, 'payload/setup/rdsetup')
RDPROBE = os.environ.get('OSB_RDPROBE') or os.path.join(ROOT, 'payload/setup/rdprobe')

def sh(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"!! {' '.join(a)}\n{r.stdout}{r.stderr}")
    return r.stdout + r.stderr

def cdhash(path):
    for l in sh('codesign', '-dvvv', path).splitlines():
        if l.startswith('CDHash='):
            return bytes.fromhex(l.split('=', 1)[1])
    sys.exit(f"no CDHash for {path}")

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'install'
    assert mode in ('install', 'remove', 'probe', 'stock')
    binary = RDPROBE if mode == 'probe' else RDSETUP
    if mode != 'stock' and not os.path.isfile(binary):
        sys.exit(f"!! missing {binary}: build the read-only probe with src/build_rdprobe.sh (requires Xcode + ldid)")
    if mode == 'probe':
        with open(binary, 'rb') as probe:
            if b'DOUBLERA1N_USB_PROBE_V2' not in probe.read():
                sys.exit('!! stale USB probe binary: V2 USB initialization is required. '
                         'Run bash src/build_rdprobe.sh or pull the workflow-built binary before booting.')
    with open(osbcfg.out('apticket.im4m'), 'rb') as source:
        ticket = IM4M(source.read())
    os.makedirs(osbcfg.WORK, exist_ok=True)
    if mode == 'stock':
        # Diagnostic control: run the unmodified Apple restore environment. It
        # may enumerate as a restore device, but NO restore commands are sent.
        for key, output, tag in (('RestoreRamDisk', 'setuprd-stock.img4', 'rdsk'),
                                 ('RestoreTrustCache', 'setuptc-stock.img4', 'rtsc')):
            with open(osbcfg.ipsw(key), 'rb') as source:
                im4p = IM4P(source.read())
            im4p.fourcc = tag
            with open(osbcfg.work(output), 'wb') as dest:
                dest.write(IMG4(im4p=im4p, im4m=ticket).output())
        print('  stock restore ramdisk baseline: original ramdisk + trust cache, no injection')
        return
    # ramdisk payload (raw APFS image)
    rd = IM4P(open(osbcfg.ipsw('RestoreRamDisk'), 'rb').read())
    try:
        rd.payload.decompress()
    except Exception:
        pass                                  # restore ramdisks are usually stored uncompressed
    raw = osbcfg.work(f'setuprd-{mode}.raw')
    open(raw, 'wb').write(rd.payload.output().data)
    mnt = tempfile.mkdtemp(prefix='dualboot-rd-')
    sh('hdiutil', 'attach', '-nobrowse', '-owners', 'off', '-noverify', '-imagekey',
       'diskimage-class=CRawDiskImage', '-mountpoint', mnt, raw)
    try:
        dst = os.path.join(mnt, 'usr/local/bin/restored_external')
        if not os.path.exists(dst):
            sys.exit("!! restore ramdisk has no usr/local/bin/restored_external")
        shutil.copyfile(binary, dst); os.chmod(dst, 0o755)
        os.makedirs(os.path.join(mnt, 'usr/local/share/dualboot'), exist_ok=True)
        open(os.path.join(mnt, 'usr/local/share/dualboot/mode'), 'w').write(mode + '\n')
        subprocess.run(['sync'])
    finally:
        sh('hdiutil', 'detach', mnt)
        os.rmdir(mnt)
    data = open(raw, 'rb').read()
    # trust cache v1: version, uuid[16], count, entries of cdhash[20] + hash_type + flags
    tc = IM4P(open(osbcfg.ipsw('RestoreTrustCache'), 'rb').read()).payload.output().data
    ver, = struct.unpack_from('<I', tc, 0); n, = struct.unpack_from('<I', tc, 20)
    assert ver == 1 and len(tc) == 24 + 22 * n, f"unexpected trust cache v{ver} len {len(tc)}"
    ents = [tc[24 + 22 * i:24 + 22 * (i + 1)] for i in range(n)]
    e = cdhash(binary) + b'\x02\x00'
    if e not in ents:
        ents.append(e)
    ents.sort()
    newtc = tc[:20] + struct.pack('<I', len(ents)) + b''.join(ents)
    open(osbcfg.work(f'setuptc-{mode}.img4'), 'wb').write(
        IMG4(im4p=IM4P(fourcc='rtsc', payload=newtc), im4m=ticket).output())
    open(osbcfg.work(f'setuprd-{mode}.img4'), 'wb').write(
        IMG4(im4p=IM4P(fourcc='rdsk', payload=data), im4m=ticket).output())
    os.remove(raw)
    print(f"  setup ramdisk ({mode}): rdsk {len(data)} bytes, rtsc {n} -> {len(ents)} entries")

if __name__ == '__main__':
    main()
