# Changelog

## Unreleased

- Added an iPhone 11 Pro Max (`d431ap`, `iPhone12,5`) firmware profile generated from iOS 27.0.1 (build `24A446`). All ten read-only firmware precheck stages passed; physical boot remains untested.
- Rejected 11 Pro-specific firmware path defaults for the Pro Max when the IPSW BuildManifest is missing.
- Added a Pro Max profile validator, identity and firmware-path regression tests, and a manual read-only macOS firmware precheck workflow.
- Documented iPhone 11 series requirements, firmware verification, and device-test limitations.
