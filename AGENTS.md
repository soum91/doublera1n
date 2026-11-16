# Repository development and release rules

- Before each release, update root `CHANGELOG.md` with the real user-visible changes. Do not use generic placeholders.
- Keep device/build-specific firmware profiles isolated by Apple board ID and iOS build. Never substitute a different model's profile or boot components.
- Run the offline unit tests and exact firmware precheck before claiming firmware preparation is supported. A precheck does not establish a successful boot, SEP support, or full jailbreak compatibility.
- Mark profile `tested: true` only after a documented physical-device boot test for the exact model and build, with a recovery procedure available.
- Do not silently update stock iOS, erase the device, or run DFU/install steps as part of tests or CI.

## Universal diagnostic export policy

All current and future diagnostic/log reports must provide Copy with clipboard read-back verification where supported and visible success/failure (never silent clipboard-only); independent native Share; native Save as plain `.txt` with Files picker (`fileExporter` or `UIDocumentPickerViewController` on iOS); and selectable full report text fallback. Include app/version, device/OS, actionable error/return codes; redact passwords, tokens, identifiers and secrets. Test cross-app paste, Share, and Save to Files on a signed physical device. Until tested, mark all paths unverified, not fixed. Preserve these requirements in both AGENTS.md and CLAUDE.md.


## Public attribution and owner privacy

Use `soum91` as the author, maintainer, developer, and publisher in all first-party metadata. Do not publish the owner's legal name, private email, or other personal identifiers in source, licenses, Sileo/FlareStore feeds, release assets, binary packages, generated docs, logs, or commits. Audit generated artifacts before publishing. Preserve legitimate third-party copyright notices. Existing bundle identifiers, app groups, and entitlements must not be silently changed, because doing so can break upgrades and stored data.

## Active standalone Pico 2 rebooter task (2026-11-15)

For any work on standalone boot, Pico 2 firmware, NAND, `fsboot`, or the jailbreak boot chain, read `standalone/pico2/CLAUDE_HANDOFF.md` and `standalone/pico2/NAND_FSBOOT.md` first. The requested target is a **Pico 2-only, no-microSD rebooter for the already installed** second Data volume on `d431ap` / `24A446`, not a new install. Host-only `fsboot` tests do not demonstrate an on-device boot, and Pico/USB flash images must not be represented as working until tested. Do not modify Preboot, APFS, NVRAM, firmware, or the phone without explicit approval and a recovery plan. Preserve stock-iOS boot, privacy restrictions, and existing desktop functionality. Document a concrete blocker when no early-boot NAND path is established; do not invent a workaround.
