# Exact-image investigation: no-SD Pico 2 boot

Date: 2026-11-16. Target: iPhone 11 Pro Max, d431ap, iOS 27.0.1 / 24A446.

This work continues the **already-installed DataB rebooter**. The second environment and Sileo previously reached the Home Screen according to the user. The November 10 ramdisk failure is historical. No installation is needed for this investigation.

## New evidence

We downloaded only BuildManifest, iBSS, iBEC, kernelcache, TXM and DeviceTree from the [exact Apple IPSW](https://updates.cdn-apple.com/2026FallFCS/585d6bab-0662-42a6-ac0f-1e0392ab92ef/iPhone12,3,iPhone12,5_27.0.1_24A446_Restore.ipsw) using HTTP ranges. No APTicket request, device connection or phone write occurred.

The BuildManifest's d431ap Erase identity specifies CPID 0x8030 and BDID 0x02. Both iBSS and iBEC containers match their respective manifest SHA384 digests. Their decompressed executable bytes are identical:

- Raw executable size: **2,842,448 bytes**.
- Raw SHA256: `9f8d8c31484800b5dad37dbbc4953d8b4a9c969d46e7b53f82414a607e143f48`.
- Internal version string: `mBoot-20457.2.37` (at 0x300).
- Load base: `0x19c050000`; code/data boundary: file offset `0x1ec000`.

Manifest `BuildString` and the embedded version string differ. Do not use a human-readable version string as the identity check. The new analyzer checks manifest identity, container SHA384 and the separately pinned raw SHA256. This is file consistency and exact-image binding, **not an implementation of Apple CMS signature verification**.

## Concrete loader references

All addresses below are **file offsets in that exact raw executable**, not runtime virtual addresses. The checked-in [machine-readable report](d431ap-24A446-iboot-audit.json) can be reproduced with `iboot_audit.py`.

| Evidence | Offset / target | Interpretation and limit |
| --- | --- | --- |
| `fsboot` authenticated command entry | table 0x1ecc20, handler 0xb28 | The handler exists in this build. Entry alone does not prove NAND access after pwned DFU. |
| `memboot` console entry | table 0x11c980, handler 0x154c | Existing command redirection can target the real fsboot handler. |
| `fsboot` direct call | 0xc8c -> 0x1838 | Filesystem boot enters a shared setup helper. |
| `boot-ramdisk` string lookup | string 0x13a826; reference 0x1a58; call 0x1a74 -> 0xa962c | Optional lookup in that shared helper. The namespace and runtime source of this key still need to be established. |
| Optional ramdisk path | 0x1ab8 -> 0xc1a2c | Same candidate `rdsk` image-loading helper used by upgrade code. |
| `/boot/ramdisk` | string 0x13b2ab; reference 0x61e8; call 0x6200 -> 0xc1a2c | This literal path is in the upgrade handler, not proof fsboot reads DataB or `/boot/ramdisk`. |
| `/boot/kernelcache` | string 0x13b2c1; reference 0x6264 | Another upgrade-path reference, not a validated staging location. |
| Ramdisk loader predicate | 0xc1a68 -> 0xc1b68 | Predicate queries selector 0x02008b00 with argument 0x50000 through 0xb4c2c. Zero returns failure before image loading. Meaning remains unresolved; **do not blindly bypass it**. |
| Candidate image load | 0xc1b20 -> 0x6a8e0 | The helper constructs `rdsk` and invokes this loader candidate. File access, image verification, volume selection and return-state semantics need tracing. |
| Shared helper early gate | 0x1878 -> 0x2624; TBZ at 0x187c | Reads a global byte at base + 0x2ca880. A zero bit skips the shared setup; its initialization is another unresolved dependency. |

These observations improve on the earlier generic `fsboot` hypothesis: there **is a concrete optional ramdisk-loading path reachable in the static fsboot call chain**. They do not demonstrate that the installed phone supplies the required path/key, that its boot policy allows this path, or that a jailbreak kernel and jbinit ramdisk will boot.

## Storage measurements

| Item | Bytes | What this establishes |
| --- | ---: | --- |
| Pico 2 onboard flash | 4,194,304 | Entire firmware and embedded data share this budget. |
| Raw stock first stage | 2,842,448 | Leaves 1,351,856 bytes before Pico firmware, alignment and metadata. |
| Raw patched first-stage candidate | 2,842,448 | Same size; host preparation succeeded against the real image. |
| zlib level 9 of patched first stage | 1,808,273 | A measurement only; no Pico decompressor is implemented. |
| Apple's current compressed kernelcache container | 21,818,243 | Current full-upload storage design cannot fit its kernel in 4 MiB even before the ramdisk. This is the stock container, not the unavailable per-device patched IMG4. |
| zlib level 9 of that kernel container | 21,798,506 | Recompressing the current compressed container does not solve the storage problem. This does not prove every future compression or architecture impossible. |

The earlier claim that a 96 MiB raw APFS ramdisk by itself proves no compressed solution can fit was too strong. The actual **first stage fits**. The existing complete upload chain does not fit in its current representation. Loading the larger boot components from the phone remains the route to investigate; do not substitute the microSD route for this goal.

Candidate SHA256: `671580b5881b4416645a4f38fabca52421dff9b6fd2322ec6950dd07315deceb`. This candidate is raw bytes, not a signed IMG4 or UF2. No first-stage candidate or Apple firmware bytes are committed.

## Implemented in this change

- `iboot_audit.py`: repeatable exact-image analysis, manifest/component validation, bounded adjacent ADRP/ADD references, direct B/BL decoding and recorded static edges. Raw, local extracted firmware and Apple HTTP range-read inputs are supported. It does not patch, connect to a phone, request a ticket or write boot files.
- `nand_fsboot.py`: refuses any stock input whose raw SHA256 differs from this exact d431ap/24A446 image. Previously, another model/build with an iBoot marker could pass preparation.
- Regression tests reject another image, mismatched build/board/chip, ambiguous identities, directory traversal, changed digests, and misdecoded branches/registers.
- CI performs offline tests; a separate exact-Apple binary audit publishes **JSON metadata only**.

Reproduce without an iPhone:

```bash
python3 -m pip install pyimg4==0.8.9 remotezip==0.12.6
python3 standalone/pico2/iboot_audit.py --apple-download
# Or reuse already-extracted stock firmware:
python3 standalone/pico2/iboot_audit.py --firmware-dir /private/firmware-parts
```

## Validation completed locally

- 61 offline tests passed, including eight new binary-analysis tests and the wrong-image preparation regression.
- Exact firmware regeneration reproduced all seven checked-in kernel/TXM record sets.
- All four setup/second-Data kernel/TXM plans verified their original words (17, 11, 145 and 16 changed words respectively).
- Existing desktop iBSS/iBEC patches and both DeviceTree edit sets applied to the exact firmware.
- Profile integrity checker passed; profile `tested` remains false.
- Real first-stage candidate preparation succeeded after the new SHA256 guard.

No fresh TSS signing check or daemon/rootfs validation was performed. These firmware checks are offline evidence, not physical boot proof.

## Next work, with concrete targets

1. Trace initialization of base + 0x2ca880 and the source/namespace of `boot-ramdisk` through 0xa962c. Establish whether a volatile setting can select a file while preserving stock NVRAM and default boot policy.
2. Resolve selector 0x02008b00 and the 0x50000 argument, then trace the volume/file context passed to 0x6a8e0. Determine read-only access to the actual Preboot volume in the pwned-DFU launch context. No arbitrary gate bypass.
3. Establish how kernel, TXM, SPTM, DeviceTree and trust cache would be supplied/patched in the same path. A ramdisk loader alone does not replace them.
4. Only then design any required **separate** one-time internal-file staging and recovery procedure. No Preboot/APFS/NVRAM writes are included or authorized by this code.
5. Integrate the verified sequence into Pico USB firmware. Until the complete chain is implemented and physically tested, there is no working no-SD UF2 to flash.
