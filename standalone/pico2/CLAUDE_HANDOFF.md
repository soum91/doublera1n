# Claude handoff: Pico 2-only doublera1n rebooter (no microSD)

**Date:** 2026-11-15 (America/Toronto)
**Status (updated 2026-11-19):** Personalized UF2 was built and validated offline for a genuine Pico 2; **not physically boot-tested**. A pinned rebuild helper and one-pass Mac runbook are available. It is a flashable-format *candidate*, not a demonstrated iPhone booter.
**Target:** the user's separate Raspberry Pi Pico 2 (RP2350A, 4 MiB flash), NOT their additional RP2354A-based DFU/PWN board. iPhone 11 Pro Max (`iPhone12,5`, board `d431ap`), installed iOS 27.0.1 (`24A446`).
**User goal:** Re-enter the **already installed** doublera1n second Data environment and jailbreak after a restart, with only the Pico 2, **without a PC, Mac, microSD module, or another fresh installation**.

## Native Micro-USB host connector feasibility (2026-11-19)

The RP2350's integrated USB controller supports host mode through the Pico 2's built-in Micro-USB connector. The user prefers a Micro-USB-to-Lightning connection instead of soldered GP12/GP13 data wiring. **Current usbliter8 firmware is PIO-host-only for the exploit**: it uses GP12/GP13 to generate the low-level A13 DFU exploit signalling, and reserves the native USB controller for USB serial/programming. A cable plugged into the built-in port cannot run the present UF2. A true one-cable design requires a verified native-USB exploit rewrite/alternative low-level host primitive, plus protected external VBUS power and correct OTG cabling; ordinary TinyUSB host support does not prove the exploit's required timing/control can be reproduced. Do not call Pico wiring electrically inherent, only a requirement of the current firmware, and do not claim a native-port jailbreak build exists. See the hardware section of RUNBOOK.md.

## Confirmed hardware and build update (2026-11-19)

- The user owns BOTH a genuine Raspberry Pi Pico 2 and a separate RP2354A DFU/PWN service board. Continue the original Pico 2 path; the 2 MiB RP2354A capacity restriction is irrelevant to the genuine Pico 2.
- The private Pico 2 NAND UF2 candidate has been compiled offline with 3,891,456 bytes of flash extent in 4 MiB, leaving 302,848 bytes. Code, tests and CI are available; flashing, USB-host electrical validation and complete phone boot are still unverified.
- See [RUNBOOK.md](RUNBOOK.md) and [BOARD_COMPATIBILITY.md](BOARD_COMPATIBILITY.md). Do not ask the user to change boards, add microSD, reinstall DataB or repeat research on the resolved static iBoot ramdisk flag. Verify genuine Pico 2 GP12/GP13 USB host wiring and protected VBUS before any iPhone connection.
- The previously observed second Data unexpected shutdown is a separate runtime issue. The read-only `collect_shutdown_diagnostics.py` can capture crash/watchdog evidence when SSH is reachable. No root cause has yet been demonstrated.

## Latest implementation update (2026-11-16)

**Start with [NAND_BOOT.md](NAND_BOOT.md).** The static ramdisk flag is resolved as enabled; the APFS default selects Preboot; paths resolve beneath a hash directory. `nand_boot.py` now prepares a transient five-path wrapper plus a missing-ramdisk guard, preserves/revalidates retagged installed assets, and emits a private local staging map. EP0 transport, exact-device checks and source integration are implemented. Continue with the actual private workspace/staging/hardware acceptance steps there; do not repeat the old unresolved-flag hypothesis. No physical NAND boot or UF2 has been demonstrated.

## Earlier binary-analysis update (2026-11-16)

Read [BINARY_FINDINGS.md](BINARY_FINDINGS.md) and [d431ap-24A446-iboot-audit.json](d431ap-24A446-iboot-audit.json) first. Exact Apple iBoot analysis located a shared, gated optional `boot-ramdisk` path reachable from fsboot. Continue from the concrete function offsets and unresolved gates there. `iboot_audit.py --apple-download` reproduces the static report without a phone or a personalized ticket. The raw first stage fits in 4 MiB; the complete current upload chain does not. No on-device no-SD boot has been demonstrated.

## Read this first

- [NAND_FSBOOT.md](NAND_FSBOOT.md): source-grounded findings on the iBoot filesystem-boot hypothesis and why it is still unverified.
- [nand_fsboot.py](nand_fsboot.py): safe, host-only patched-iBEC **first-stage candidate preparation**, not a booter.
- [README.md](README.md): the current, separate microSD boot-data/exporter design. **Do not mistakenly implement the SD route as the requested solution.**
- [../../lib/patch_iboot.py](../../lib/patch_iboot.py): `memboot` -> `fsboot` command-table patch, `--local`, `--no-autoboot`, `--keep-cmds`.
- [../../lib/mk_osbjb.py](../../lib/mk_osbjb.py): actual jailbreak ramdisk and kernel generation, and `--no-fsboot` in the **existing** second-Data build.
- [../../lib/boot_chain.py](../../lib/boot_chain.py), [../../dualboot.py](../../dualboot.py): normal boot requires pwned DFU, iBSS, iBEC, multiple firmware images, trust cache, a 96 MiB APFS jbinit ramdisk, DeviceTree, SEP, patched kernel, and `bootx`.
- [../../src/rdsetup.c](../../src/rdsetup.c): installer uses Preboot read-only and writes its setup information to DataB; it does **not** prove that patched boot images already exist at an iBoot-accessible NAND path.
- [../../docs/diagnostics/2026-11-10-d431ap-usb-probe-handoff.md](../../docs/diagnostics/2026-11-10-d431ap-usb-probe-handoff.md): historical USB failure investigation. **Do not confuse that older probe with this newer, distinct objective.**

## Verified facts versus unproven ideas

**Source verified:** the installed second Data volume is different from the custom boot chain. `dualboot.py boot` calls `lib/boot_chain.py --osbjb` and resends the kernel/ramdisk/etc. No DataB reinstallation is part of that boot-only path. `mk_osbjb.py` builds and signs a custom APFS ramdisk; `patch_iboot.py` supports an `fsboot`-related patch, but the current jailbroken iBEC is built with `--no-fsboot`.

**User-reported device state:** the second environment, jailbreak, and Sileo were previously installed/booted. Do not require running `install` again or claim a successful current boot without a new, verified device trace.

**NOT verified:** the patched A13 iBoot invoked from pwned DFU can read modern iOS 27 APFS/Preboot boot objects; the required personalized patched kernel, firmware, trust caches, DeviceTree, and custom jbinit ramdisk are currently stored in an early-boot-readable place; a one-file payload can bootstrap them; Pico 2's 4 MB is sufficient for a complete standalone image; stock `fsboot` would boot the jailbroken DataB or satisfy SEP/TXM/SPTM constraints. **An `fsboot` command executing successfully would NOT prove a jailbroken boot.**

## Claude: prioritized implementation and research assignment

1. **Audit the exact first-stage capabilities** for `d431ap` / `24A446`: inspect the correct iBEC/iBoot code paths, APFS/Preboot filesystem loaders, `fsboot` entry, device-tree and trust-cache sourcing, boot manifest matching, SEP, SPTM/TXM, and restrictions during remote (pwned DFU) boot. Record concrete functions, references, evidence and limitations; do not use older 32-bit iBoot documentation as if it proves iOS 27 support.
2. **Inventory required boot components and their true location** in the existing installed workspace and on the phone, without modifying the phone. Specifically establish how the `jbinit`/PID 1 ramdisk and kernel patches would be made available early enough. Do not assume an installed DataB contains bootable prekernel assets, or that iBoot can read DataB.
3. **Evaluate feasible Pico-only strategies**: (a) load validated pre-existing NAND-resident images through modified iBoot, (b) stage a small persistent preboot image set only if genuinely necessary and separately authorized, (c) shrink/re-architect jbinit startup to remove the 96 MiB ramdisk dependency, or (d) conclude that no verified no-storage path exists. State actual bytes/storage needs, firmware interfaces, and how boot personalization and integrity are retained. Distinguish proof from hypotheses.
4. **Implement only offline-verifiable primitives first** in `standalone/pico2/` on a dedicated branch, ideally with tests and CI. Reuse `nand_fsboot.py` where appropriate. Require exact `d431ap` / `24A446` matching, fail-closed image validation, and a recovery procedure. Only produce a UF2 when it includes a real, validated boot sequence and is clearly marked device-untested until physical proof.
5. **Report a hard blocker precisely**, if found: name the missing interface, evidence needed to resolve it, and the least-invasive fallback. Do not respond with repeated DFU tests, a fake boot-success indicator, or an unbootable one-file UF2.

## Mandatory safety and workflow rules

- **Do not** run `install`, `remove`, `setenvnp`, APFS volume operations, OTA/restore, persistent NVRAM edits, or automatic Preboot writes.
- Any proposal to alter a device partition, Preboot or boot policy requires a separate implementation/recovery review **and explicit user approval** before device writes. Avoid any operation risking the existing iOS 27.0.1.
- Do not flash the `nand_fsboot.py` output to the Pico, treat it as a complete IMG4, or tell the user it is known to boot. It is raw candidate bytes only.
- No private APTickets, boot bundles, device identifiers, full legal names, tokens, or other device-specific material in Git, public CI artifacts, logs, or releases. Use public publisher attribution `soum91` only.
- Preserve existing desktop `boot.sh`, `dualboot.py`, installer, root `AGENTS.md` rules, and root `CLAUDE.md` diagnostic/release requirements.
- Update root `CHANGELOG.md` for any release-relevant code changes. Run exact unit tests and firmware prechecks. Do not equate CI/precheck success with an on-device boot.
- Work on the no-SD Pico-only objective first. The previously implemented microSD exporter is a **separate fallback** and must not be presented as accomplishing the user's request.

## Concrete acceptance criteria

- A documented, build-specific proof that the loader can access and verify every required boot image without external storage, **or** an evidence-based explanation why this cannot currently be done.
- A testable, fail-closed boot sequence including kernel, trust cache, security firmware, DeviceTree, and jbinit startup, not merely pwned DFU or `bootx`.
- Physical proof of the jailbroken second Data environment and Sileo/SSH startup before calling the project a working standalone rebooter. The first on-device experiment must have an independently verified stock-iOS recovery path.

**Current deliverable:** Continue the research and code from `NAND_FSBOOT.md`. The no-microSD bootstrap path remains **unproven**.
