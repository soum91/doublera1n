#!/usr/bin/env bash
# Rebuild a PERSONALIZED, device-untested Pico 2 standalone NAND booter.
# Requires local private PicoNAND export and a Mac with Homebrew, CMake,
# the Arm GNU embedded toolchain, and Pico SDK 2.2.0 (clones SDK if missing).
set -euo pipefail

PICO="${PICO:-$HOME/Desktop/PicoNAND}"
DB_REPO="${DB_REPO:-$HOME/doublera1n-pico}"
BASE="${PICO_BUILD_ROOT:-$HOME/pico2-nand-build}"
SDK="${PICO_SDK_PATH:-$BASE/pico-sdk}"
UP="$BASE/usbliter8"
ADD="$BASE/usbliter8-standalone"
OUT="${PICO_UF2_OUT:-$HOME/Desktop/doublera1n-pico2-NAND-DEVICE-UNTESTED.uf2}"

[[ -f "$PICO/nand-first-stage.raw" && -f "$PICO/stage-map.json" && -f "$PICO/nand_device_config.h" ]] || { echo 'Missing PicoNAND private export' >&2; exit 1; }
[[ -f "$DB_REPO/standalone/pico2/integrate_pico.py" ]] || { echo 'Missing updated doublera1n-pico checkout' >&2; exit 1; }
[[ ! -e "$OUT" ]] || { echo "Refusing to overwrite existing output: $OUT" >&2; exit 1; }
for command in git python3 cmake patch arm-none-eabi-gcc; do
  command -v "$command" >/dev/null || { echo "Missing $command. See RUNBOOK.md prerequisites." >&2; exit 1; }
done
mkdir -p "$BASE"
if [[ ! -d "$SDK/.git" ]]; then
  [[ ! -e "$SDK" ]] || { echo "SDK path exists but isn't a git checkout: $SDK" >&2; exit 1; }
  git clone https://github.com/raspberrypi/pico-sdk.git "$SDK"
fi
if [[ -e "$UP" || -e "$ADD" ]]; then
  echo "Build trees already exist in $BASE. Use a NEW PICO_BUILD_ROOT instead of reapplying patches." >&2
  exit 1
fi
# Pin exactly the versions from the successful offline build report.
git -C "$SDK" checkout a1438dff1d38bd9c65dbd693f0e5db4b9ae91779
git -C "$SDK" submodule update --init --recursive
git clone https://github.com/JoshAtticus/usbliter8.git "$UP"
git -C "$UP" checkout 479dbbf4ad80e4a454e0779d1b4d1ec5eb0d7bd5
git -C "$UP" submodule update --init --recursive
git clone https://github.com/jackspence7/usbliter8-standalone.git "$ADD"
git -C "$ADD" checkout 6a742806e79445e573f2bfc553b83d5fc300a6fa
for f in main.c led.c led.h CMakeLists.txt; do
  patch -d "$UP" -p1 < "$ADD/patches/$f.patch"
done
cp "$ADD/new-files/autoboot.c" "$ADD/new-files/autoboot.h" "$ADD/new-files/make_boot_uf2.py" "$UP/"
python3 "$DB_REPO/standalone/pico2/integrate_pico.py" --source-root "$UP" --private-export "$PICO"
export DBNAND_PRIVATE_EXPORT="$PICO"
cmake -S "$UP" -B "$UP/build" -DPICO_BOARD=pico2 -DPICO_SDK_PATH="$SDK"
cmake --build "$UP/build" --parallel 4
python3 "$UP/make_boot_uf2.py" "$UP/build/usbliter8.uf2" "$PICO/nand-first-stage.raw" "$OUT"
python3 - "$OUT" "$PICO/nand-first-stage.raw" <<'PY'
from pathlib import Path
import hashlib, struct, sys, zlib
path, raw = map(Path, sys.argv[1:])
data = path.read_bytes(); image=raw.read_bytes()
assert len(data)%512==0 and len(image)==2_842_448, 'unexpected UF2 or image size'
FLASH_BASE=0x10000000; FLASH_END=FLASH_BASE+4*1024*1024
MAGIC=(0x0A324655, 0x9E5D5157); END=0x0AB16F30
blocks=[]; count={}
for start in range(0,len(data),512):
    b=data[start:start+512]; m0,m1,flags,addr,n,idx,total,fam=struct.unpack_from('<8I',b)
    assert (m0,m1)==MAGIC and struct.unpack_from('<I',b,508)[0]==END, 'invalid UF2 framing'
    assert n<=476, 'invalid UF2 payload'
    blocks.append((flags,addr,n,idx,total,fam,b[32:32+n])); count[fam]=count.get(fam,0)+1
family=max(count,key=count.get)
flash={}; furthest=FLASH_BASE
for flags,addr,n,idx,total,fam,payload in blocks:
    if fam!=family:
        continue  # preserve SDK E10 workaround block
    assert flags&0x2000 and FLASH_BASE<=addr and addr+n<=FLASH_END, 'out-of-bounds flash block'
    assert n==256, 'expected 256-byte main-family flash payload'
    assert addr not in flash, 'overlapping flash blocks'
    flash[addr]=payload; furthest=max(furthest,addr+n)
image_base=FLASH_BASE+0x100000
header=flash.get(image_base,b'')
assert header[:8]==b'L8BOOT01', 'missing header'
size,crc=struct.unpack_from('<II',header,8)
assert size==len(image) and crc==(zlib.crc32(image)&0xffffffff), 'boot image metadata mismatch'
assembled=bytearray()
for addr in range(image_base+0x100, image_base+0x100+len(image),256):
    assert addr in flash, 'missing image flash block'
    assembled.extend(flash[addr])
assert bytes(assembled[:len(image)])==image,'embedded boot image mismatch'
print('UF2 BLOCK VERIFICATION: PASS')
print('Boot-image SHA256:',hashlib.sha256(image).hexdigest())
print('UF2 container bytes:',len(data))
print('Flash upper extent:',furthest-FLASH_BASE,'of',FLASH_END-FLASH_BASE,'bytes')
print('Remaining flash:',FLASH_END-furthest,'bytes')
print('Physical iPhone boot: NOT TESTED')
PY
echo "Personalized UF2: $OUT"
echo 'DO NOT publish this file: it includes phone-specific boot data.'
