# Claude development instructions

Read and obey root `AGENTS.md`, preserving all existing safety, firmware-specific and release rules. Do not claim device compatibility from CI or offline tests alone.

For diagnostics, require Copy with read-back verification and visible success/failure, native Share, native Save as plain `.txt` via Files picker (`fileExporter` or `UIDocumentPickerViewController` on iOS), and selectable complete report text. Include app/build, device/OS, actionable return codes, and redact secrets. Test signed-device cross-app paste, Share and Save before claiming success; otherwise explicitly mark unverified.

For every release, use real commit/diff evidence and update `CHANGELOG.md` and GitHub release notes consistently. Never invent changes or suppress failed checks. Rebuild-only notes must specify actual toolchain, signing or packaging differences.

## Active device failure handoff (2026-11-10)
Read `docs/diagnostics/2026-11-10-d431ap-usb-probe-handoff.md` before editing iBoot/USB/ramdisk/dualboot boot logic. Target is iPhone 11 Pro Max d431ap build 24A446. USB disappears after bootx; no verified ramdisk or jailbreak. Separate observed traces from hypotheses and preserve data. Do not claim success from offline tests.

## ACTIVE TASK: Pico 2-only no-microSD reboot of installed DataB (2026-11-15)

**Read [standalone/pico2/CLAUDE_HANDOFF.md](standalone/pico2/CLAUDE_HANDOFF.md) in full before writing or changing Pico/bootloader code.** This is the current implementation assignment, and the earlier 2026-11-10 USB failure handoff is historical context, not a directive to repeat those experiments.

Goal: Raspberry Pi Pico 2 (RP2350A, 4 MB flash) alone should re-enter an *already-installed* second Data jailbreak on iPhone 11 Pro Max `d431ap` / iOS 27.0.1 `24A446`, without a Mac/Windows machine, microSD, or reinstallation. The no-SD path is **not yet proven feasible**. Follow the handoff's evidence-first gates, implement only verifiable primitives, and document blockers instead of pretending an `fsboot` patch or host CI proves a jailbreak boot. No automatic phone/Preboot/NVRAM changes or unverified UF2 flashing; any phone-write step requires explicit user authorization.

### Exact-image continuation (2026-11-16)

Start with `standalone/pico2/BINARY_FINDINGS.md`: real d431ap/24A446 iBoot analysis found the optional `boot-ramdisk` loader path and its unresolved gates. Continue tracing those exact functions; do not repeat the historical USB probe or treat the generic fsboot handoff as the latest research. No phone write or standalone boot was performed.

### NAND loader implementation continuation (2026-11-16)

Read `standalone/pico2/NAND_BOOT.md` before continuing. The configuration flag and Preboot/hash directory selection are statically resolved; candidate preparation, transient five-path overrides, a missing-ramdisk guard, private installed-asset export and guarded Pico EP0 transport/source wiring now exist. The original successful private workspace and a physical device trace remain necessary. Do not claim a working rebooter, flash a generic candidate, or repeat the superseded unresolved-gate investigation.
