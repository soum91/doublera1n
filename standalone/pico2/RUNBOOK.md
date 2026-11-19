# Pico 2 / doublera1n standalone NAND rebooter: full Mac runbook

> **Correct hardware confirmed (2026-11-19):** The user owns **two separate boards**: a genuine Raspberry Pi Pico 2 (RP2350A with 4 MiB flash) and an RP2354A-based DFU/PWN service board. **Use the genuine Pico 2 for this project.** The existing 3,891,456-byte personalized UF2 flash extent fits Pico 2, leaving 302,848 bytes. The RP2354A's 2 MiB limitation does **not** block this Pico 2 route; it applies only if someone tries to flash the separate DFU/PWN board. See [BOARD_COMPATIBILITY.md](BOARD_COMPATIBILITY.md). Image fit is verified offline; physical boot and safe USB-host wiring are not yet verified.

Target for THIS BUILD: the user's separate genuine Raspberry Pi **Pico 2** (RP2350, **4 MiB** flash), iPhone **11 Pro Max** (`d431ap`) on **iOS 27.0.1 (`24A446`)** with **second Data already installed**. This uses the phone's internal **Preboot**, not microSD. The secondary iOS/jailbreak is NOT reinstalled.

**Reality check:** The export has already passed five SHA256 checks. You have verified the matching Preboot hash directory exists, the phone is SSH-reachable while running DataB, and Preboot shows ~6 GiB available. `PicoNAND` dates from Nov 16 and no UF2 was found in your home directory. The private UF2 compiled Nov 16 was in another development environment and has not been physically boot tested. This procedure is a cautious experimental attempt, **not a guaranteed jailbreak**.

**Do not share** `~/Desktop/PicoNAND`, private APTickets, `stage-map.json`, `nand_device_config.h`, or the personalized UF2 publicly.

**Recommended execution order:** First do **Section 1**, then **Section 3** (build), **Section 4** (flash), and **Section 5** (validate electrical host wiring). **Only when those are ready**, return to **Section 2** and explicitly stage files while DataB/SSH still works, then proceed to **Section 6**. The section numbering groups phone preparation, rather than requiring risky Preboot writes before hardware preparation.

## 0. Preserve the already-working iPhone

Keep it connected to the Mac, charging and currently booted into the second Data environment until **after** the verified staging and UF2 build. Retain the known-working desktop `boot.sh`, your original workspace `~/doublera1n-usb-537622e/dualboot-work` and the exact matching local firmware profile. Have a separate stock-iOS recovery option and do not accept any restore/update/erase prompt. Do not run `dualboot.py install`, `remove`, OTA, or modify APFS roles/NVRAM.

## 1. Check the export and Preboot (no writes)

Pull the newest `main` into your separate `~/doublera1n-pico` checkout (keep the original working checkout untouched). In Mac Terminal:

```sh
cd ~/doublera1n-pico
git pull --ff-only
python3 standalone/pico2/stage_preboot.py
```

The script validates exact `d431ap`/`24A446`, the 96-character uppercase manifest hash, a 20-character content ID, five file SHA256s, **matching expected mount-relative and iOS paths**, existing mounted Preboot directory, and ensures no staging or incomplete directory exists. It refuses any mismatch. **Default does not write to iPhone.**

## 2. One-time isolated Preboot staging (DEVICE WRITE)

**Defer this step until the UF2 is verified and the USB host wiring is checked.** Only after reviewing the printed destination and choosing the one-time Preboot write:

```sh
python3 standalone/pico2/stage_preboot.py --stage
```

`--stage` creates **only** a new `/private/preboot/<96HEX>/doublera1n-pico2/<20hex>/` directory: it writes into a uniquely named `.incomplete` directory, copies each IMG4 via SSH, **reads each back** and verifies full SHA256 and size, then atomically renames the complete directory. It does not overwrite Apple's existing `System`, `usr`, `private`, `AppleInternal`, or the `/private/preboot/active` marker. It never runs `rm`, never changes NVRAM, mounts, APFS roles or installations.

If any operation fails, the incomplete directory is retained for manual inspection; nothing is automatically deleted. **Do not reboot until the result is understood.** Stage success is not proof the bootloader can read those files. This is a real Preboot write, which carries risk despite directory isolation.

## 3. Rebuild the missing personalized Pico UF2 (MAC ONLY)

Requires: Homebrew, `cmake`, `patch`, `python3`, `git`, official Arm GNU embedded toolchain, and SDK. For a Mac with Homebrew:

```sh
brew install cmake ninja libusb
brew install --cask gcc-arm-embedded
arm-none-eabi-gcc --version
```

The earlier offline build used Pico SDK **2.2.0** and Arm GCC **15.2.Rel1**. Homebrew may provide a newer Arm compiler; if it does, the resulting build is **not identical** to the earlier binary and must be re-validated. The build helper pins Pico SDK and both upstream project commits to the earlier successful offline report.

Your new `~/doublera1n-pico` checkout is ready. To refresh and build:

```sh
cd ~/doublera1n-pico
git pull --ff-only
bash standalone/pico2/build_pico2_uf2.sh
```

The build helper creates `~/pico2-nand-build` and checks out the exact usbliter8 and standalone add-on revisions, applies four upstream patches, integrates the project-specific Pico USB transport, builds the `pico2` target, and combines it with your original `nand-first-stage.raw`. It then parses the UF2 and checks addresses, block framing, CRC32, exact embedded first-stage bytes, firmware reservation and flash extent.

Expected output:

```
~/Desktop/doublera1n-pico2-NAND-DEVICE-UNTESTED.uf2
```

Important: **The UF2 container may be about 5.8 MB even though the Pico 2 has only 4 MiB flash.** UF2 stores 256-byte payloads inside 512-byte transfer blocks. The documented earlier build occupied **3,891,456 bytes** of flash leaving **302,848 bytes** free. The *new* build helper measures its actual output and fails if the flash range exceeds 4 MiB. Do not flash if verification fails.

If build dependencies are unavailable or the exact-source patch does not apply cleanly, stop; do **not** fall back to an ordinary usbliter8 UF2 or an unverified `iBSS.boot` (those will not reproduce doublera1n's NAND path).

## 4. Flash the Pico 2 (does not touch the phone)

1. Unplug the Pico 2 from the Mac. Leave the iPhone disconnected from any unverified Pico wiring.
2. Hold the Pico 2 **BOOTSEL** button while connecting its Micro-USB port to the Mac. Release BOOTSEL when the `RP2350` storage drive mounts.
3. **Before copying anything**, run the read-only verifier in Mac Terminal from `~/doublera1n-pico`:
   ```sh
   python3 standalone/pico2/verify_uf2_for_board.py \\
     --board pico2 \\
     --uf2 ~/Desktop/doublera1n-pico2-NAND-DEVICE-UNTESTED.uf2
   ```
   Stop on any error. This validates framing and flash extent for the declared Pico 2, but cannot prove USB wiring or iPhone boot.
4. Copy the **personalized, verified** `doublera1n-pico2-NAND-DEVICE-UNTESTED.uf2` onto the Pico 2 `RP2350` volume. The drive disappearing/restarting is normal; it is **not proof the iPhone booted**.
5. If Pico firmware fails, enter BOOTSEL again to reflash it. Do not use firmware intended for the separate RP2354A DFU/PWN service board or Waveshare RP2350-USB-A board.

## 5. Wire an actual USB host interface (HARDWARE STOP)

The Pico 2 **Micro-USB connector is the Pico's own USB device/programming/serial port, NOT the host connector for your iPhone**. The tested usbliter8 Pico 2 pin assignments are **GP12 = D+** and **GP13 = D-** for the independent PIO-USB host. The iPhone also needs **GND and a properly protected/current-limited 5V USB VBUS supply**, with safe common ground. It is **not** safe to use the Pico's 3V3 rail as iPhone power, reverse-feed USB supplies, or trust unknown Lightning cable wire colors. The cable's actual data pins, VBUS/current and board power path must be verified electrically before use. You need a known-good **Lightning** data interface and suitable soldered host breakout; a normal Micro-USB-to-Lightning cable alone does NOT create this GP12/GP13 host port.

This project has not verified the proposed hardware assembly, power arrangement, USB electrical signaling, or a complete jailbroken boot. Do not physically connect the phone to unfinished or unverified wiring.

## 6. First on-device test, after hardware sign-off

The intended flow from the standalone add-on is: iPhone in Recovery, connect to powered Pico USB host, follow the Pico LED prompts to reach DFU, perform usbliter8 pwned DFU, send **2,842,448-byte personalized first stage**, await Recovery, submit `memboot`, then the modified iBoot attempts to load the five staged images from Preboot and enter installed DataB. Serial debug appears on the Pico Micro-USB virtual COM/TTY port (the standalone add-on documents `/dev/cu.usbmodem*` on macOS). No laptop should be needed for *routine* boots once this path physically works, but the first test should use the Mac for logging and recovery.

**Do not use LED 'success' or a `memboot` USB ACK as proof of jailbreak.** Only count success if the iPhone actually enters the existing second Data environment and jailbreak services (such as SSH and Sileo) work. The candidate still has unresolved real-device uncertainties about iBoot APFS path access and full SEP/SPTM/peripheral firmware handoff.

## 7. If it fails

- **Export/preflight mismatch:** stop; do not regenerate or reinstall DataB simply to bypass validation.
- **Stage error:** leave `.incomplete` folder for investigation. Do not remove any other Preboot files.
- **Toolchain/compiler/CMake error:** save build log; no phone action is necessary.
- **Pico BOOTSEL not recognized:** verify a data-capable Micro-USB cable and USB port. Re-enter BOOTSEL; do not connect the iPhone.
- **Pico exploit/Recovery handoff fails:** power off safely and revert to the established Mac `boot.sh` method. Avoid repeated phone resets without a recovery plan.
- **Boot hangs after `memboot`:** the real Preboot image loader, security firmware boot dependencies and runtime APFS behavior have not been proved. Capture the Pico serial log; do not erase/restore or alter the iPhone's Apple boot files.

**Bottom line:** your screenshots finish the export, hash and Preboot-hash-directory validation. The remaining route is one isolated on-phone staging operation, a personalized UF2 rebuild, safe external USB wiring, and a real boot test. The toolchain can be prepared on your Mac now; physical wiring cannot be safely completed by software alone.
