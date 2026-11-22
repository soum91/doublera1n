# DataB SEP recovery: pwnerblu ACM protocol bridge and exact d431ap / 24A446 blockers

**Research date:** 2026-11-22. **Target:** iPhone 11 Pro Max (A13, `d431ap`), iOS 27.0.1 (`24A446`), **already installed** doublera1n second Data (`DataB`). No repartitioning, restore, stock-iOS update, or reinstallation is needed or authorized for this investigation.

**Status: research only. No functioning SEP-enabled DataB boot, passcode, Face ID, Apple Pay, Apple Account login, or keybag integration has been demonstrated.** Do not claim that the public screenshot establishes such support. Preserve the existing known-good SEP-less boot path.

## The original report

The researcher @pwnerblu reported an iPhone SE 2 **tether-downgraded to iOS 15.5**, activating natively with **iOS 27 SEP**. The described fix is a protocol bridge in `AppleSEPCredentialManager`: format its SEP request as iOS 16 would. Public mirrored report: https://www.teapawt.net/pwnerblu (and https://www.xitter.cf/pwnerblu).

An actual *related* open-source implementation exists at https://github.com/pwnerblu/iphonese-ios16/blob/main/obsoletepatch/sepfix.c. Its header explicitly describes an **experimental iOS 16 ACM -> iOS 15 SEP** adapter, with four instruction changes covering the outgoing message body and incoming response header/metadata/request ID. It is in **`obsoletepatch/`**, and the current IPSW build script excludes `sepfix`. Thus it is **not** the new iOS 15.5 -> iOS 27 implementation, not a working patch for iOS 27.0.1, and not proof of full SEP services. No published source for the exact screenshot's newer bridge was located in the reviewed public repositories as of this research. Do not copy undocumented binary patches, donor offsets or unlicensed source into doublera1n.

## Why this is different from DataB

The screenshot describes **cross-version request-envelope compatibility between an older OS and a newer SEP**. Our DataB normally boots the **existing iOS 27.0.1 stock System** with an alternate data volume, and its boot plan **intentionally substitutes or suppresses SEP-facing functions**.

Confirmed from this repo, not inferred from the screenshot:

1. `lib/boot_chain.py` uploads `SEP.img4` and executes `rsepfirmware`; `lib/mk_osb.py` copies the real SEP firmware. **A SEP firmware image being sent is not proof that its runtime endpoints become usable** in DataB. The OS B source comments explicitly report that the SEP OS does not come up.
2. `profiles/d431ap-24A446/kernel-boot-jit.json` has **135 patch records**, including **52 edits forming 26 two-instruction AppleSEPCredentialManager method stubs**. Notably `sendSEPCommand` and `processSCRDResponsePayload` are both changed to immediate success returns. These two functions are central to the request/response route discussed in the report. A protocol bridge cannot operate through functions currently stubbed out.
3. The same file patches `AKSUserClient::start` to skip its SEP-dependent call and replaces `AKSUserClient::externalMethod` with a selector-7 shim that synthesizes `noPin` and `beenUnlocked` state. These return/status shims are **not evidence of a functioning SEP or legitimate data-protection unlock**.
4. `profiles/d431ap-24A446/kernel-osb.json` has **7 SEP-less patches**, including a two-word `AppleSEPKeyStore` helper that **always reports SEP not booted**, plus no-panic patches and an SEP sleep-state workaround.
5. `device/osb-boot.sh` intentionally disables `corerepaird` and `seserviced`, given missing SEP/xART endpoints and crash/loop hazards. `lib/mk_osbjb.py` starts patched `securityd`, `coreauthd`, `ctkd`, `lockdownd`, and `mobileactivationd` because the normal SEP-dependent paths are not currently usable. The project uses `obkeychain` and a non-native activation fallback.

These interdependent changes make it unsafe to remove the single `sep-booted.false` patch or paste an ACM legacy envelope patch and then attempt passcode, Face ID, Apple Pay or account sign-in. Doing so could panic or boot-loop DataB and may corrupt its separate keychain state; the risk of changing shared SEP/security state must be treated as potentially affecting the stock environment.

## What must be proved, in order

**Phase 0: no-write baseline.** Preserve a known-good `boot.sh`-booted environment, exact original `24A446` IMG4/patch profiles, and a stock-OS recovery path. Capture redacted, private logs about `AppleSEPManager`, the `sks` endpoint, `scrd`, `AppleSEPKeyStore`, `AppleCredentialManager`, `sep-booted`, and relevant panic/watchdog entries while DataB is already running. Avoid keybag files, passcodes, pairing material and account tokens in reports. Static patch presence is **not** runtime proof.

**Phase 1: real SEP initialization and endpoint readiness.** Identify where the loaded SEP firmware fails to establish `sks`, `scrd`, `xART` and other expected endpoints in the patched OS B. Verify the exact firmware/image and power-state sequencing without disabling protective checks. This is the primary blocker; the screenshot does not solve it.

**Phase 2: restore real request/response behavior in an isolated, opt-in experimental kernel.** Only after Phase 1, selectively remove the 26 forced-success ACM stubs and other AKS / SEP boot shortcuts *in a separate named experimental artifact*. Keep the normal, working `osbjb` build bit-identical and restore it on failure. Use exact-image patch validation; no donor offsets or success-forging stubs.

**Phase 3: protocol comparison only if actual requests fail.** Compare `AppleSEPCredentialManager` request and response envelopes for **the real d431ap iOS 27.0.1 System and installed SEP firmware**, then decide whether a bridge is required. pwnerblu's public `obsoletepatch/sepfix.c` can guide the methodology (outbound body vs reply header), **not** provide valid A13/iOS 27 patch bytes.

**Phase 4: legitimate DataB keybag support.** Apple's documented user/device keybag protections are tied to Secure Enclave and passcode-derived keys. Having a live endpoint does not migrate the stock user keybag to DataB or safely create one. See https://support.apple.com/en-au/guide/security/sec6483d5760/web. Never transplant stock keybags, fake a passcode-unlocked state or modify SEP anti-replay state.

**Phase 5: one service at a time.** Validate authenticated activation and Apple Account login separately; then a fresh isolated DataB keychain, passcode creation/unlock, Face ID enrollment, secure element/Apple Pay and persistence after reboot. Do not infer support for one service from success of another.

## Current disposition

The pwnerblu finding is a **promising ACM protocol reference**, not a DataB SEP unlock. The strongest immediately actionable research target is **why the actual SEP endpoints fail during the current DataB boot**; only then does cross-version message bridging matter. Do not alter boot, kernel, KeyStore, Preboot, NVRAM or DataB keybags as part of this document.
