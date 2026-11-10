# Changelog

## Unreleased

- Added opt-in `probe-usb --variant stock` and `--variant minimal` diagnostics for the iPhone 11 Pro Max black-screen boot. The stock variant repackages Apple's unmodified RestoreRamDisk and RestoreTrustCache without injecting a binary and passively watches post-boot USB; the minimal variant removes peripheral firmware while retaining SPTM, TXM and both trust caches. Both reject implicit installation and require `--boot` before transmitting a chain. The standard installer and default probe behavior are unchanged.
- Added a host-side `rd=md0` artifact check before experimental boot, explicit Recovery/DFU exclusion from the stock USB observer, and offline checks that the stock baseline neither mounts nor injects into the ramdisk. Neither alternative is physically validated; seeing a USB product ID would not by itself prove successful ramdisk startup.
- Added read-only post-`bootx` diagnostics after the first physical iPhone 11 Pro Max trial reached `bootx` but produced a black screen and no USB probe response: the boot chain now reports the actual `irecovery -c bootx` exit/output and observes Apple USB product-ID transitions. A command being issued is no longer presented as proof that the custom kernel/ramdisk booted.
- The USB probe's timeout report now cross-checks raw Apple USB enumeration and `irecovery -q` status so a failed `usbmuxd`/`iproxy` handshake is distinguishable from disappearance from USB. The no-UART installer is still not implemented or validated.
- Fixed an early iBSS handoff diagnostic failure on Macs: `boot_chain.py` now uses the caller's virtual-environment Python for the `usbliter8ctl` sender, stops and prints its actual error if the send fails, and reports detected USB mode after Recovery timeout. Recovery A/B/C/D USB product IDs are recognized. This is not evidence of a successful physical boot or a completed jailbreak.
- Added an opt-in, read-only USB restore-ramdisk transport experiment for Macs whose pwnDFU boards expose no UART/CDC serial device. Its standalone ramdisk listener and host `iproxy` client test only a diagnostic handshake; no APFS volume setup or ticket extraction runs.
- Added a manual macOS workflow to build and sign the standalone diagnostic binary. Actual iPhone 11 Pro Max boot and USB return transport remain untested; the normal installer still requires UART.
- Included the workflow-built, signed diagnostic binary under `payload/setup/rdprobe`, eliminating manual artifact copying on Macs running the experiment.
- Added an iPhone 11 Pro Max (`d431ap`, `iPhone12,5`) firmware profile generated from iOS 27.0.1 (build `24A446`). All ten read-only firmware precheck stages passed; physical boot remains untested.
- Rejected 11 Pro-specific firmware path defaults for the Pro Max when the IPSW BuildManifest is missing.
- Added a Pro Max profile validator, identity and firmware-path regression tests, and a manual read-only macOS firmware precheck workflow.
- Documented iPhone 11 series requirements, firmware verification, and device-test limitations.
