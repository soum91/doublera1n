# Changelog

## Unreleased

- Added an opt-in, read-only USB restore-ramdisk transport experiment for Macs whose pwnDFU boards expose no UART/CDC serial device. Its standalone ramdisk listener and host `iproxy` client test only a diagnostic handshake; no APFS volume setup or ticket extraction runs.
- Added a manual macOS workflow to build and sign the standalone diagnostic binary. Actual iPhone 11 Pro Max boot and USB return transport remain untested; the normal installer still requires UART.
- Added an iPhone 11 Pro Max (`d431ap`, `iPhone12,5`) firmware profile generated from iOS 27.0.1 (build `24A446`). All ten read-only firmware precheck stages passed; physical boot remains untested.
- Rejected 11 Pro-specific firmware path defaults for the Pro Max when the IPSW BuildManifest is missing.
- Added a Pro Max profile validator, identity and firmware-path regression tests, and a manual read-only macOS firmware precheck workflow.
- Documented iPhone 11 series requirements, firmware verification, and device-test limitations.
