# Claude development instructions

Read and obey root `AGENTS.md`, preserving all existing safety, firmware-specific and release rules. Do not claim device compatibility from CI or offline tests alone.

For diagnostics, require Copy with read-back verification and visible success/failure, native Share, native Save as plain `.txt` via Files picker (`fileExporter` or `UIDocumentPickerViewController` on iOS), and selectable complete report text. Include app/build, device/OS, actionable return codes, and redact secrets. Test signed-device cross-app paste, Share and Save before claiming success; otherwise explicitly mark unverified.

For every release, use real commit/diff evidence and update `CHANGELOG.md` and GitHub release notes consistently. Never invent changes or suppress failed checks. Rebuild-only notes must specify actual toolchain, signing or packaging differences.

## Active device failure handoff (2026-11-10)
Read `docs/diagnostics/2026-11-10-d431ap-usb-probe-handoff.md` before editing iBoot/USB/ramdisk/dualboot boot logic. Target is iPhone 11 Pro Max d431ap build 24A446. USB disappears after bootx; no verified ramdisk or jailbreak. Separate observed traces from hypotheses and preserve data. Do not claim success from offline tests.
