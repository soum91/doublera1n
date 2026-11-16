# Pico 2 no-SD NAND boot candidate

This branch preserves successful installation commit `537622e`. Read [WORKING_BASE.md](WORKING_BASE.md) for the original generated profile and export command. Its desktop boot libraries and patch plans take precedence over earlier examples in this document.

**Status: personalized Pico 2 UF2 compiled and verified offline. Preboot staging and physical boot validation remain pending.** See [BUILD_VALIDATION.md](BUILD_VALIDATION.md) for the measured build.

Target: already-installed doublera1n DataB on d431ap / iOS 27.0.1 / 24A446, with a 4 MiB Pico 2. No reinstall, new microSD, stock OS update or automatic phone writes are involved.

## What was resolved

| Previous question | Exact-image result | Implementation |
| --- | --- | --- |
| Does the optional ramdisk loader require a policy bypass? | No such bypass is indicated: selector 0x02008b00 resolves to concrete inline boolean **true**. The false record is a fallback and loses to the concrete record. | `iboot_audit.resolve_preconditions` resolves the registered descriptors rather than guessing or NOPing a branch. |
| Which filesystem/volume does default fsboot setup select? | `f08f4(0)` selects the registered `apfs` driver. Its mount callback at 0x8e2a8 passes role 0x10 to 0x8aa78, which compares the APFS superblock role at 0x3c4. This is Preboot. | Keep the default boot-device/partition and volume selection; do not guess a disk number or redirect to encrypted DataB. |
| Where does fsboot resolve its paths? | Helper 0x332e8 constructs `%s/%s` from `/boot` and a 48-byte hash encoded using uppercase hex. Its alternate path reads `%s/active`. | The private export maps files beneath the **existing installed-ticket BootManifestHash directory**, not the root of Preboot. It never changes `active`. Actual selected-prefix confirmation remains necessary on the phone. |
| How can already-patched components load without missing runtime-KPF assembly? | RAM environment keys exist for `boot-path`, `dt-path`, `tc-path`, `txm-path`, and `boot-ramdisk`. | A new 696-byte handler (with a 20-character content directory) fits in the unused 748-byte memboot body. It sets those five RAM values with iBoot's own string setter, flags=0, and tail-calls fsboot. No persistent NVRAM writer is called by the injected handler. |
| Can the desktop restore-tagged images be used unchanged? | Filesystem loading expects different types for kernel, DT and TC. | Retag `rkrn→krnl`, `rdtr→dtre`, `rtsc→trst`; retain `trxm` and `rdsk`. Preserve every payload byte and the installed IM4M. Revalidate kernel/TXM/DT against the exact stock firmware and patch plans first. |
| Will a failed ramdisk load stop boot? | The helper at 0xc1a2c can clear both ramdisk globals on failure and still return zero. | Guard its shared-fsboot call: require both a loaded address and size before continuing. A missing ramdisk must not proceed into a forced `jb=md0` kernel. |
| Does this need a Recovery bulk uploader? | The new arrangement sends only one raw first stage, then `memboot`. Larger files are supplied by the phone. | `nand_transport.c` uses only EP0: 192-byte DFU chunks, CUSTOM_BOOT, ABORT, Recovery re-enumeration, then the vendor console command. CPID, BDID and private expected ECID are checked before transfer and again in Recovery. |
| How does that connect to Pico firmware? | The standalone add-on already calls `autoboot_boot` after exploitation. | `integrate_pico.py` wires that entry to the own-code bus adapter. It verifies the exact add-on source hash, preserves attribution, keeps the private header outside Git, and replaces the final boot-success indication with an explicit unverified-handoff message. |

These resolve **static research and implementation gaps**. They do not prove APFS access, complete stock security-firmware loading, the selected hash directory, or a jailbroken startup on hardware.

## Private preparation on the original installation Mac

Run this in the updated repository on the Mac that has the **successful installed workspace**. It automatically finds one installed d431ap/24A446 workspace under the repository's `dualboot-work`, honoring `DUALBOOT_HOME`. `--workspace /path/to/workspace` or `--work-root /path` can select another location.

```bash
.venv/bin/python3 standalone/pico2/nand_boot.py export \
  --output ~/Desktop/PicoNAND
```

This does **local preparation only**, without USB or SSH. The output must be a new directory outside this Git repository and the source workspace. If multiple workspaces match or original generated boot images are missing, it stops. Do not reinstall DataB to satisfy it.

The private folder contains:

- `nand-first-stage.raw`: exact-image patched first-stage candidate with transient path overrides and a missing-ramdisk guard.
- `preboot-files/`: five retagged images from the existing successful `build/osbjb` set.
- `stage-map.json`: file hashes, exact proposed staging destination, private device identity, candidate CRC/hash and measured layout.
- `nand_device_config.h`: expected-device binding for the local Pico build. Keep this header and all output private.

The exporter checks the installed ticket's CPID/BDID/ECID and exact encoding; every source IMG4 must use that same ticket. It verifies the source manifest and component digests, reconstructs kernel/TXM patch results, and reproduces the DataB DeviceTree edits. Ramdisk/TC structural validation does not replace a device boot test or prove their internal filesystem contents. No Apple signature verification implementation is claimed; the patched image-validation callback is part of the existing approach.

The three tag changes preserve the installed manifest bytes, keeping its BootManifestHash stable. The separate stage-map path is:

`/private/preboot/<installed IM4M SHA384 in uppercase>/doublera1n-pico2/<content-id>/`

The content ID depends on the private ticket and all five output hashes. Files for different preparations get separate directories. **No phone copier is included.** The installed hash directory and the path selected by iBoot must be checked before any staging write. Never replace existing stock boot objects or `active`, change APFS roles, or save boot variables to NVRAM.

## Pico source integration

Use your own local usbliter8 source with the [MIT standalone add-on](https://github.com/jackspence7/usbliter8-standalone) already applied. Upstream exploit source is not vendored here. The reviewed `autoboot.c` SHA256 is:

`45d332b333d4604e8af38736b551856c8585ff04601dc8a9240029f385786d3f`

```bash
python3 standalone/pico2/integrate_pico.py \
  --source-root /path/to/standalone-usbliter8 \
  --private-export ~/Desktop/PicoNAND
```

This changes local firmware source only. It does not build or flash firmware. When that source is later configured, `DBNAND_PRIVATE_EXPORT` must point to the private export directory so the device header can be included without copying it into Git. The source integration is fail-closed on an unreviewed add-on revision, a changed candidate, a mismatched private header or an unexpected success-indicator block.

The first stage occupies **2,842,448 bytes**. With the add-on's 1 MiB firmware reservation and 256-byte header, it ends at **3,891,280** in a **4,194,304-byte** flash, leaving **303,024 bytes**. A final actual firmware build must still be measured to ensure it ends below the reserved image offset; this session did not build that UF2. Do not flash raw candidate bytes as a UF2.

The transport's positive status means **the command was handed off**, never that DataB, jbinit or Sileo booted. There is no on-phone boot proof from an EP0 acknowledgement.

## Validation performed

- **84 offline tests**, including ARM64 instruction execution with mocked iBoot services, every setter-failure path, the false-success ramdisk guard, descriptor precedence, image retag/ticket preservation, USB phase failures, wrong-phone and device-swap rejection, and private-header isolation.
- Portable C transport compiled with `-Wall -Wextra -Werror`; the adapter compiled against the checked upstream API contract. No ARM SDK binary was built.
- Real exact-Apple first-stage preparation succeeded. The checked-in selfcheck JSON contains metadata only, no personalized images.
- The private asset verifier was exercised against the real Apple manifest/kernel/TXM/DT and rejects a changed kernel. Ramdisk/TC inputs in that exercise were structural fixtures, not the user's actual installed boot set.
- Source integration was applied successfully to the actual upstream source plus the reviewed MIT add-on in a scratch checkout, using a dummy private identity fixture. No firmware was built or flashed.
- Existing exact firmware-profile checks and all four kernel/TXM patch plans were rechecked without connecting a phone.

Unicorn tests explicitly model PAC instructions as no-ops. They verify emitted control flow, argument setup and failure handling; they do not establish real pointer authentication, MMU/cache state, USB timing, image verification or APFS behavior.

## What still requires the user's hardware and original files

1. Run the private export using the original successful workspace. That workspace, its installed ticket and jbinit ramdisk are **not available in this session**. They cannot be reconstructed from public Apple firmware alone.
2. Inspect the exact stage map against the phone's existing mounted Preboot/hash directory and verify an independently known stock-iOS recovery route. Staging is a separate, reviewed one-time copy into the isolated new directory; it is not reinstallation.
3. Build and size-check the actual Pico 2 firmware using those private files; only then prepare a clearly device-untested test UF2.
4. Physically demonstrate that the pwned-DFU first stage reads the selected Preboot objects, loads stock SPTM/SEP/peripherals together with the staged five assets, and reaches DataB with jbinit and Sileo/SSH. Until that trace exists, do not mark the profile tested or call this a working no-SD rebooter.
