# doublera1n: iPhone 11 Pro Max d431ap iOS 27.0.1 boots iBEC but USB ramdisk never enumerates

Date: 2026-11-10. Status: **still blocked; no demonstrated jailbreak**. Handoff for independent investigation by Claude. Do not mistake a successful DFU/bootx exit for a functioning ramdisk or jailbreak.

## Target and physical setup
- Repository: `soum91/doublera1n` (fork of `34306/doublera1n`).
- Device: iPhone 11 Pro Max, `iPhone12,5`, board `d431ap`, iOS **27.0.1**, build **24A446**.
- Mac host (user also has a Windows computer); usbliter8 RP2350-family DFU/pwn board.
- A major early connectivity trap was found: board had been powered by a **wall charger**, not the host's data-capable USB port, and at another point the phone was connected directly rather than through the board. These were corrected. Use computer USB data to board and correct phone-to-board wiring for pwned DFU.
- Board DFU/PWN indicator flashes and a successful pwned mode has been observed with `PWND: usbliter8`.
- The phone can black-screen after boot handoff.

## Repro / command
From updated local fork and configured `.venv`:
```sh
git pull --ff-only
./.venv/bin/python3 dualboot.py probe-usb --variant probe --build 24A446 --boot
```
Earlier command without `--variant probe`:
```sh
./.venv/bin/python3 dualboot.py probe-usb --build 24A446 --boot
```
This is a **diagnostic probe**, not a jailbreak install command. Do not claim success until a ramdisk USB session and postboot state are observed.

## Observed behavior from prior user tests
- Early attempts failed at `[1] iBSS`, `[!] no (healthy) Recovery device`; hidden iBSS failures/generic exception reporting were addressed in source (see `af60171`).
- Subsequent progress: pwned DFU -> iBSS -> iBEC -> firmware/kernel payloads accepted. `bootx exit=0` reported.
- **Immediately after boot handoff the USB device disappears and the probe cannot talk to a ramdisk.** Neither host probe nor restored service becomes available.
- Multiple stock/minimal/lean-kernel/bootarg variants failed at the same handoff. User described ~18 ResetCounter reports and no usable panic log. Device stayed black/unreachable on attempts.
- Because the actual ramdisk never confirmed connection, the jailbreak/second Data boot path is **unverified** for this device/build.

## Source fixes attempted, not user-verified on-device
- `af60171`: reveal earlier iBSS errors.
- `5db907b`, `10a739fe`, `fdce8fb`, `015954d`, `0b2c91c`: additional probe/boot-order diagnostics and fallbacks in local history.
- `183a5cc2abcaf0ed42679747abaecc7050fddf1a`: corrected diagnostic image that previously used a TCP listener in place of `restored_external` without initializing USB device mode; adds USB initialization, loopback, permissions, signing changes. Reported 34 offline tests and local macOS build/signature checks passing. **No subsequent successful phone USB enumeration was provided.**
- Compare code against upstream and inspect produced ramdisk binary, not only script exit codes.

## Questions and next steps for Claude
1. Verify full USB gadget bring-up on A13/d431ap iOS build 24A446: hardware power/data path, host re-enumeration, USB descriptors, iBoot handoff, `restored_external`, daemon initialization and socket path.
2. Determine whether `bootx exit=0` reflects the host command being accepted versus the target kernel actually booting. Add a definitive *stage marker* on the device side.
3. Capture high-resolution host USB enumeration and iBoot/recovery events around the handoff. Differentiate host transport loss, kernel panic, and userspace service failure.
4. Confirm ramdisk and kernelcache compatibility, entitlements/signatures and `d431ap`-specific boot arguments. Where possible compare known working A13 build/device.
5. Keep probe code **read-only/non-destructive** until robust USB recovery. Do not alter/delete DataB or Preboot contents without explicit separate user authorization.
6. Redact serial/UDID/ECID and user real name in reports and artifacts. Request a fresh complete probe log (redacted) after latest `183a5cc` before declaring fixed.

## Evidence limitations
Earlier screenshot sequence and a diagnostic `Archive.zip` were provided in the prior chat, but the archive bytes are **not present in this current handoff**. Do not invent its contents. The observations above are the dated discussion summary and commit history; obtain the actual diagnostic log from user or existing repo before making a firmware-specific claim.

Expected success: pwned DFU handoff, ramdisk USB enumeration and stable command/response, then independently verified second-Data boot and jailbreak artifacts. Current status stops before USB probe success.
