# Personalized Pico 2 build validation

On 2026-11-16 the user's private export was validated and compiled into a personalized, device-untested Pico 2 UF2. Physical jailbreak startup remains pending.

- Validated all five staged IMG4 file hashes, sizes and types against the private export map.
- Confirmed matching installed-ticket bytes across the files and matching CPID, BDID and private ECID.
- Reproduced the exported first-stage bytes with the successful `537622e` base's bootloader patcher and the exported path overrides.
- Built upstream usbliter8 `479dbbf4ad80e4a454e0779d1b4d1ec5eb0d7bd5` with standalone add-on `6a742806e79445e573f2bfc553b83d5fc300a6fa` and this branch's NAND integration.
- Used Pico SDK 2.2.0 (`a1438dff1d38bd9c65dbd693f0e5db4b9ae91779`) and Arm GNU Toolchain 15.2.Rel1, targeting `pico2` / RP2350 ARM Secure.
- The firmware's rounded flash extent is 58,368 bytes, below its 1 MiB reservation. The first stage is 2,842,448 bytes. The combined rounded flash extent is 3,891,456 bytes of 4,194,304, leaving 302,848 bytes.
- Independently parsed all final UF2 blocks. Verified magic, family, bounds, numbering, absence of overlapping ARM blocks, original firmware payloads, header, CRC32 and exact embedded first-stage bytes. Preserved the SDK's RP2350-E10 absolute-family workaround block verbatim.
- The final UF2 file occupies 5,803,008 bytes including UF2 container overhead.

The host picotool dependency emitted GCC C++ `-Wfree-nonheap-object` warnings while compiling. The target firmware compiled and linked successfully. No phone staging, Pico flashing or physical boot was performed in this environment.

The UF2 and private assets remain private. They are excluded from public Git and CI artifacts. An existing Preboot hash directory, its mount state and free space must be inspected before the one-time staging copy. Booting this candidate requires those five files at the private staging map's paths.
