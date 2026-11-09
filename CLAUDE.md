# Claude development instructions

Read and obey root `AGENTS.md`, preserving all existing safety, firmware-specific and release rules. Do not claim device compatibility from CI or offline tests alone.

For diagnostics, require Copy with read-back verification and visible success/failure, native Share, native Save as plain `.txt` via Files picker (`fileExporter` or `UIDocumentPickerViewController` on iOS), and selectable complete report text. Include app/build, device/OS, actionable return codes, and redact secrets. Test signed-device cross-app paste, Share and Save before claiming success; otherwise explicitly mark unverified.

For every release, use real commit/diff evidence and update `CHANGELOG.md` and GitHub release notes consistently. Never invent changes or suppress failed checks. Rebuild-only notes must specify actual toolchain, signing or packaging differences.
