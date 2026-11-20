# Two-board distinction: Raspberry Pi Pico 2 versus RP2354A DFU/PWN board

## Confirmed user hardware (2026-11-19)

The user owns **both** a standalone genuine Raspberry Pi Pico 2 and a separate RP2354A-based DFU/PWN service board. **The Pico 2 is the project target**, and the validated 3,891,456-byte boot image fits its 4 MiB flash (302,848 bytes remaining). The RP2354A limit applies only to the *other* board and must not be presented as blocking the user's Pico 2 work. Neither the Pico 2 USB-host electrical interface nor iPhone NAND loading has been physically validated.

## Why this matters

**2026-11-20:** At the user's explicit request, a separate compressed-source
port foundation now exists in [RP2354A_PORT.md](RP2354A_PORT.md). The real stage
compresses to 1,841,206 bytes including block headers and passes portable C
decode/mock-upload checks. This does not change compatibility of the existing
Pico UF2: no RP2354A firmware, board mapping or physical boot is verified.

The user also has a black A12/A13 DFU/PWN service board identified as RP2354A-based, with USB-C (PC/target) and Lightning connectors. The present NAND UF2 work was built for a **genuine Raspberry Pi Pico 2** (RP2350A + **4 MiB** off-chip flash), exposed GPIOs GP12/13 and a Micro-USB programming port. These are different boards. Never use a Pico 2-specific UF2 with the RP2354A service board.

Raspberry Pi documents the RP2354A's **2 MiB in-package flash**:
- https://www.raspberrypi.com/documentation/microcontrollers/microcontroller-chips.html
- https://www.raspberrypi.com/news/rp2350-a4-rp2354-and-a-new-hacking-challenge/

The candidate built 2026-11-16 has **3,891,456 bytes of flash extent**, including the **2,842,448-byte** personalized first-stage iBoot blob. Both exceed the RP2354A's 2,097,152-byte default flash space (extent by 1,794,304 bytes; raw first stage by 745,296 bytes). No additional flash on the exact service-board PCB has been identified or validated. Firmware capacity, target-side USB data pin routing, 5V VBUS power switching, GPIO/LED controls and BOOTSEL procedure are unknown for this custom board.

**Status on the separate RP2354A board only: NOT compatible, not flashed, not tested.** No assertion of extra flash or a usable GP12/GP13 Lightning path is justified without the PCB schematic or electrical verification. A UF2 container of ~5.8 MB is not its flash extent; the validated *flash extent* is ~3.89 MiB.

## Read-only capacity check

On the Mac, after the private firmware has been built:

```sh
cd ~/doublera1n-pico
python3 standalone/pico2/verify_uf2_for_board.py \
    --board rp2354a \
    --uf2 ~/Desktop/doublera1n-pico2-NAND-DEVICE-UNTESTED.uf2
```

Expected: **STOP**, because the image exceeds 2 MiB. For a **genuine** Pico 2, specify `--board pico2` instead. A PASS only confirms UF2 extent relative to the declared capacity, not compatibility with actual connected hardware.

`picotool info -a` may be used read-only in BOOTSEL to inspect a connected board, but cannot replace PCB identification and may report the embedded program's metadata rather than trustworthy unused flash capacity. Use `picotool save -a` only after reviewing its options to back up an existing firmware privately, never publish its output. Do not erase or overwrite the existing PWN board firmware to experiment.

## What an RP2354A port actually requires

1. Confirm the exact service-board hardware revision, any additional flash IC, MCU variant and its currently working firmware. Safely identify BOOTSEL, PC vs target USB ports and existing board recovery method; preserve original firmware.
2. Trace the phone-side USB D+/D-, VBUS protection/power switch, ground, and reset/LED GPIOs. The retail Pico 2's GP12/GP13 wiring is **not** automatically applicable to the service board.
3. If the only flash is 2 MiB, implement and validate an actual compressed/streamed first-stage transport under this limit, with RAM use within RP2354A bounds; compression alone cannot be assumed to fit or work. If separate flash exists, prove its map and firmware access first.
4. Build and verify an RP2354A-specific CMake board/UF2 target, rather than labeling a `PICO_BOARD=pico2` image compatible. Verify memory layout and no overlap with bootrom or existing recovery functionality.
5. Only after the hardware, firmware, flash and separate stock-iOS recovery checks are passed, consider an on-device boot test. The patched iBoot Preboot/APFS and kernel/SEP/TXM handoff remain **physically unverified**, even on a genuine Pico 2.

## Separate random shutdown issue

A phone that powers off some time after the second OS boots is a **runtime** fault, not proof that the RP2354A can or cannot run the initial loader. Distinguish an actual power-off from a kernel panic/watchdog reboot using uptime, panic-full/analytics logs and a Mac USB/serial trace. Do not claim a fix from the existing USB reset retry commit (`a492ffd`) without matching evidence. Keep the successful desktop boot baseline `537622e` intact and avoid reinstalling DataB.

**Neither device has had a confirmed standalone NAND-to-jailbreak reboot from this firmware.**
