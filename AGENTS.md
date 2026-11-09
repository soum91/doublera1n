# Repository development and release rules

- Before each release, update root `CHANGELOG.md` with the real user-visible changes. Do not use generic placeholders.
- Keep device/build-specific firmware profiles isolated by Apple board ID and iOS build. Never substitute a different model's profile or boot components.
- Run the offline unit tests and exact firmware precheck before claiming firmware preparation is supported. A precheck does not establish a successful boot, SEP support, or full jailbreak compatibility.
- Mark profile `tested: true` only after a documented physical-device boot test for the exact model and build, with a recovery procedure available.
- Do not silently update stock iOS, erase the device, or run DFU/install steps as part of tests or CI.
