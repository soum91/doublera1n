# doublera1n Pico 2 standalone rebooter (development)

**Hardware target:** Raspberry Pi **Pico 2**, RP2350A, 4 MB onboard QSPI flash, no onboard microSD socket. **Phone target:** iPhone 11 Pro Max, `d431ap`, iOS `27.0.1` build `24A446`, with *second Data volume already installed*. The existing `soum91/doublera1n` Mac boot is the reference.

**STATUS: IMPLEMENTATION IN PROGRESS, NOT A WORKING UF2. DO NOT FLASH THIS AS AN IPHONE BOOTER.** This directory currently implements a complete read-only boot-file exporter, portable boot-plan parser, CRC preflight, and ordered stage runner abstraction. The missing hardware pieces are an SPI microSD/FatFs reader, an Apple USB Recovery bulk image uploader, and the attachment of this runner to the upstream usbliter8 PIO-USB exploit and DFU helper. No physical boot has been demonstrated.

## Why `boot.sh` is not just one command

When the second environment is already installed, `boot.sh` calls `dualboot.py boot`, which calls `lib/boot_chain.py --osbjb`. The resulting boot chain still transmits **every boot image each time**. The correct image and command order is defined by `FULL` in `boot_bundle.py` and mirrored from `lib/boot_chain.py`: raw iBSS in pwned DFU, iBEC + `go`, all required IMG4 firmware (without `StaticTrustCache` for OS B), `RestoreTrustCache`, jailbroken 96 MB APFS ramdisk, DeviceTree, SEP, patched kernel, `bootx`. Device transition waits are also needed. It does **not** reinstall DataB.

The **96 MB uncompressed ramdisk** alone makes the 4 MB onboard flash insufficient. Boot files must be stored on a *separate* microSD card. `surrealboot` and `usbliter8-standalone` implement one-image tethered boot, not this full transport. The vanilla usbliter8 PIO-USB implementation only exposes EP0 control transfers through its current `bus_control_xfer`; `irecovery -f` for IMG4 requires a separate Recovery bulk data transfer implementation. Without that, a UF2 containing only the first iBSS would strand the iPhone before the jailbreak boot.

## Completed: export from the installed workspace

On the **Mac used for the successful install**, after pulling this repository:

```bash
python3 standalone/pico2/boot_bundle.py export \
  --board d431ap --build 24A446 \
  --work-root ~/dualboot-work \
  --output ~/Desktop/BOOT.BIN --dry-run

# When ready to produce the local per-device boot data (still not bootable without Pico firmware):
python3 standalone/pico2/boot_bundle.py export \
  --board d431ap --build 24A446 \
  --work-root ~/dualboot-work \
  --output ~/Desktop/BOOT.BIN
python3 standalone/pico2/boot_bundle.py inspect ~/Desktop/BOOT.BIN
```

The exporter requires one workspace with `installed=true`, matching board/build, the installed APTicket and every generated `build/osbjb/` file. It copies **only** the boot files and commands into a little-endian `BOOT.BIN` and checks CRC32 + SHA256. It never invokes DFU, never touches APFS, never contacts the iPhone, and never changes the source workspace. `BOOT.BIN` is **device-specific** and must **never be committed, posted, or uploaded to GitHub**.

If `~/dualboot-work` does not include the original successful installation workspace, a new personalized image bundle cannot safely be reconstructed from nothing. Do not call `install` merely to generate this bundle.

## Portable boot-plan data format (v1)

`BOOT.BIN` begins with a 56-byte header (`DBPICO01`, version 1, count, 16-byte NUL board, 16-byte NUL build, 64-bit little-endian total size), followed by 104-byte entries (`name[32]`, `action[16]`, `offset:u64`, `size:u64`, `post_delay_ms:u32`, `crc32:u32`, `sha256[32]`), then 512-byte-aligned files. No compression: the Pico should stream files from a FAT-formatted SD card without loading whole firmware images into RAM. `boot_plan.c` parses the format, rejects wrong phone/build, checks nonoverlapping extents, checks CRC32 for every stage before sending, then calls callbacks in exact order. It has no Apple USB sender of its own yet. SHA256 is verified by the Python host tool; the portable C preflight uses CRC32 for accidental corruption.

Build the **native offline verifier** (Linux/macOS/Windows with C compiler):

```bash
cc -std=c11 -O2 -Wall -Wextra -Werror -o inspect_bundle \
  standalone/pico2/inspect_bundle.c standalone/pico2/boot_plan.c
./inspect_bundle ~/Desktop/BOOT.BIN
python3 -m unittest discover -s tests -p 'test_pico2_boot_bundle.py' -v
```

The C verifier is a host-only test utility, **not** RP2350 firmware.

## Hardware plan (no wiring or flashing yet)

- Pico 2's **Micro-USB B** port remains connected to a power source or PC for configuration and logs. The existing usbliter8-compatible **PIO-USB host** uses **GP12 (D+)** and **GP13 (D-)** for the iPhone data lines.
- An **SPI microSD reader** would use a *separate* SPI interface, for example **GP16 (MISO), GP17 (CS), GP18 (SCK), GP19 (MOSI)**, using a 3.3 V-safe reader. These are **proposed pins**, not validated hardware wiring.
- The iPhone's 5 V VBUS requires a properly protected, current-limited **5 V host supply/switch**. Do **not** connect the iPhone directly to the Pico's 3V3 rail or use an unidentified cable. A power-only Micro-USB cable cannot provide the required phone data lines on GP12/13.
- Flashing a Pico 2 UF2 requires a **Pico 2-specific** build. Do not flash Waveshare USB-A firmware. BOOTSEL ROM recovery remains available if the Pico firmware fails, but rewiring errors can physically damage equipment.
- The existing pwnDFU board and the separate Pico 2 are not the same device; the standalone design intends to incorporate pwnDFU into the Pico 2, based on *upstream* usbliter8. No hardware connection to a phone should be attempted until a bootable firmware is verified and the power interface is wired properly.

## Upstream work to integrate (licenses respected)

- [usbliter8](https://github.com/JoshAtticus/usbliter8): proven Pico 2 pwnDFU PIO-USB foundation. Upstream source has no redistributable LICENSE; do not vendor its C files without permission. Apply a separate patch or integrate as a dependency after license review.
- [surrealboot](https://github.com/batuvatu/surrealboot): single-payload pwnDFU and DFU helper; Pico 2 target listed **untested**. Cannot simply repurpose its one-image sender.
- [usbliter8-standalone](https://github.com/jackspence7/usbliter8-standalone): one-image `DFU_DNLOAD`/`CUSTOM_BOOT` sender and Recovery -> DFU helper. Not yet capable of `irecovery -f` IMG4 bulk uploads or `bootx`.
- [no-OS-FatFS-SD-SDIO-SPI-RPi-Pico](https://github.com/carlk3/no-OS-FatFS-SD-SDIO-SPI-RPi-Pico): RP2350-capable SD driver. Its licensing and SD port selection need to be integrated and verified separately.

## Safety and privacy

Never distribute APTickets, device-unique jailbreak ramdisks, boot bundles or the contents of `~/dualboot-work`. Keep backup and stock-iOS recovery plan. The original doublera1n second environment is SEP-less, so standalone boot cannot restore passcode/iCloud capability. Passing a host test does not prove a jailbreak boot.
