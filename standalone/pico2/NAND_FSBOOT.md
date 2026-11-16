# Pico 2 internal-storage boot experiment (d431ap / 24A446)

**Status: offline proof-of-concept only. NO WORKING JAILBREAK BOOTER OR UF2.**

Goal: explore an RP2350-only first stage that uses *existing iPhone internal boot storage*, without an external microSD card and without reinstalling `DataB`.

## NAND boot implementation (2026-11-16)

[NAND_BOOT.md](NAND_BOOT.md) supersedes the earlier research-only candidate below: it documents the resolved static loader flag and Preboot/hash path, a real transient-path first-stage wrapper, a ramdisk failure guard, retagged private asset preparation and EP0 Pico transport. No physical no-SD boot or UF2 is verified. The older `nand_fsboot.py` remains a stock-only probe and must not be confused with `nand_boot.py`.

## Exact-image progress (2026-11-16)

[BINARY_FINDINGS.md](BINARY_FINDINGS.md) now records verified d431ap/24A446 iBoot offsets, a shared optional ramdisk-loading path, unresolved gates and measured first-stage storage. The preparer is now bound to the exact stock raw SHA256; an iBoot marker alone is insufficient. See `iboot_audit.py` for reproducible analysis. These are binary findings, not an on-device boot.

## What the actual doublera1n source says

- `lib/patch_iboot.py` already implements `memboot` command-table redirection to `fsboot`, `--local` (pretend NAND boot) and `--no-autoboot` (stay in console). These are **patches**, not proof that the iPhone 11 Pro Max can boot from NAND after a pwned DFU jump.
- `lib/mk_osbjb.py` explicitly invokes `patch_iboot.py --no-fsboot`, and it separately generates a **96 MiB APFS ramdisk** with PID 1 `jbinit`, its trust cache, and the patched kernelcache. The current boot path needs that ramdisk to start the second environment.
- `lib/boot_chain.py --osbjb` uploads a full firmware set, the ramdisk, DeviceTree, SEP, trust cache, and patched kernel. `bootx` success alone is not proof of a successful startup.
- `src/rdsetup.c` mounts the shared Preboot volume **read-only** during install and writes setup data to `DataB`. An installed `DataB` volume is **not evidence** that the generated ramdisk and patched boot files are stored where iBoot can read them before the kernel runs.

Historic references show `fsboot` can load stock kernelcache from a boot filesystem and `upgrade` can load staged images. But older 32-bit / legacy upgrade layouts are NOT validated for A13 / iOS 27.0.1. For modern release iBEC, `fsboot` may be disabled unless the command table is patched. A custom loader would need to verify *exact* BootManifest, APFS paths, image verification, SPTM/TXM, trust cache, DeviceTree, kernel patches and SEP behavior.

Sources:

- https://theapplewiki.com/wiki/Fsboot_(iBoot_command)
- https://theapplewiki.com/wiki/Boot-command_(iBoot_variable)
- https://theapplewiki.com/wiki/Upgrade_Mode
- https://www.pmbonneau.com/multiboot/introduction.html (legacy reference only)

## What this patch provides

`nand_fsboot.py` is a **host-only preparation and source-audit tool**. It invokes the existing, build-matched `lib/patch_iboot.py` on an already available *decrypted stock* iBEC raw image with:

- `--local`: request NAND/local boot behavior;
- `--no-autoboot`: leave recovery console available rather than automatically booting;
- `--keep-cmds`: preserve `go`/`rsepfirmware` handlers;
- **no** `--no-fsboot`: enable the patched `memboot` -> `fsboot` mapping;
- stock-oriented verbose args **without** `jb=md0` or `rd=md0`.

The output is **raw first-stage candidate bytes**, NOT `.img4`, `.uf2`, or a complete jailbreak. The code refuses to overwrite the input, refuses to write into Git working tree, checks patch-log evidence, and has no USB, NVRAM, APFS or phone-write operations. The candidate is deliberately unable to use the existing second-data jailbreak by itself.

### Audit without an iPhone

```bash
python3 standalone/pico2/nand_fsboot.py audit
```

### Prepare a candidate from original locally decrypted iBEC (not yet for flashing)

```bash
python3 standalone/pico2/nand_fsboot.py prepare \
  --stock-ibec-raw /absolute/path/to/iBEC.stock.raw \
  --output /absolute/private/path/NAND_FSBOOT_CANDIDATE.raw
```

A missing original decrypted raw iBEC means preparation must stop. Do not feed the `iBEC.img4` wrapper as raw input and do not substitute another iPhone model's files. This command **does not touch the connected iPhone**. The Pico's flash budget must be measured against a final firmware before any attempt to embed a personalized stage.

## What is still required for no-SD standalone boot

1. **A real NAND-read verification:** confirm the patched iBoot's `memboot` / `fsboot` logic can reach a boot filesystem when started from A13 pwned DFU. The candidate has *not* been run on-device.
2. **Boot-component availability:** prove the actual required images can be read from an early-boot-accessible storage path. `DataB` alone does not establish this. If the images must be placed in Preboot, that would be a **separate one-time staging step** requiring its own safety/recovery design and explicit authorization before any write. This proof-of-concept performs no staging.
3. **Patched kernel and security firmware:** implement proper iOS 27 SPTM/TXM and kernel patching while loading from internal storage. The repository has `--kpf`/entry-hook primitives, but no verified integration for this standalone path.
4. **PID 1 / jbinit:** preserve the current rootless jailbreak startup by loading its boot ramdisk from an accessible volume, or invent and validate a new launch path that does not depend on the ramdisk. There is no evidence the currently installed second Data volume provides either automatically.
5. **RP2350 integration and recovery:** integrate standalone usbliter8 with a verified early bootloader handoff, and enforce the exact board/build/ECID and fail-safe return to stock iOS. Hardware validation required. **Do not flash experimental output as a phone booter.**

This experiment avoids microSD *only if* the phone can be made to supply the needed early-boot files without endangering the existing firmware. It is not a promise that modern APFS/SEP/iBEC will allow that.
