# RP2354A service-board port: compressed boot source

Updated 2026-11-20. User explicitly requested exploring the separate black
DFU/PWN board as a standalone booter. This is additional research; the working
desktop path and genuine Pico 2 target remain intact. **No board firmware,
board compatibility or physical boot is established.**

## Implemented and measured offline

Recovered the first stage from the existing private personalized Pico UF2,
validated its framing, length and original CRC, and tested independent zlib
blocks against the real payload. No private images, identifiers or hashes are
included in Git.

| Item | Bytes |
| --- | ---: |
| Original first stage | 2,842,448 |
| DBZBLK01 encoded stage, including all headers | 1,841,206 |
| Remaining in 2 MiB for firmware and metadata | 255,946 |
| Remaining with hypothetical 128 KiB firmware + 256-byte metadata | 124,618 |
| Decoder/source context on the test host | 41,200 |

128 KiB is a design budget, **not a linked ARM firmware measurement**. The
context size is host-ABI-specific. Stack, USB state, multicore buffers, code,
boot metadata and target RAM/flash layout still need an actual target build.
The current Pico image retains its 1 MiB image offset and will NOT fit this
board. Compression does not make that existing UF2 compatible.

`compression_audit.py --uf2 /private/path/to/candidate.uf2` performs read-only
extraction, compression and round-trip checks. It prints sizes only and emits
no firmware or private payload. CRCs detect accidental corruption; they do not
authenticate firmware. This does not replace the exporter's exact firmware,
patch-plan, ticket or expected-device checks.

`block_source.c` decodes one block at a time with pinned miniz inflate, without
heap allocation. Both compressed and raw fallback blocks are bounded to 32 KiB.
It checks lengths, version, record count, zlib completion, consumed input and
per-block CRC before exposing decoded bytes. Supply its caller-owned state in
static storage, not a small core stack. The encoded input must stay immutable.

`dbnand_run_source` accepts an immutable replayable byte reader. It checks the
whole decoded image CRC before any USB operation, rewinds and uploads in
192-byte chunks, then checks the upload pass CRC before CUSTOM_BOOT. A reader
failure or changed source cannot proceed to CUSTOM_BOOT or memboot. The
existing memory-image API remains available and uses the same checked path.
Existing exact-device checks apply before DFU upload and again in Recovery.

## Host validation

- The actual private payload passed two full C decoder passes with exact byte
  comparison, then passed C decoder -> C transport -> mocked USB with an exact
  uploaded SHA256 comparison. No USB hardware was involved.
- Strict C compilation (`-std=c11 -O2 -Wall -Wextra -Werror`) and regression
  tests cover block boundaries, raw fallback, malformed/truncated/oversized
  blocks, preflight corruption, reader failure and source mutation.
- All 35 targeted decoder, compression, transport, board-preflight and Pico
  integration tests passed. A full-suite comparison found the identical 11
  failures and 26 errors on untouched main and this branch (164 vs 176 tests,
  five skipped on each). These baseline dependency/desktop-test issues remain;
  the full suite is not green. No new full-suite failure names appeared.
- No fresh exact-Apple firmware precheck or ARM link was performed: the runtime
  has no `ipsw` or Arm GCC toolchain. No profile was marked tested/supported.
- Fixed an existing verifier mismatch discovered with the real private UF2:
  Pico SDK E10's absolute-family workaround block uses numbering independent
  of the ARM secure blocks. The verifier now recognizes that specific record
  without counting its address toward flash extent. Capacity checks remain.

## Experimental host format (not accepted by existing firmware)

All integers are unsigned little-endian. The 32-byte header contains magic
`DBZBLK01`, version=1, raw length, block size=32768, record count, whole-image
CRC32 and reserved=0. Each record has a 12-byte header: stored size (bit 31
means raw fallback), raw size, raw CRC32, followed by stored bytes. Compressed
records contain complete independent zlib streams. The final block may be
short. Trailing bytes, incomplete streams and extra decoded bytes are errors.

## Remaining board work, in order

1. Identify the exact service-board revision from readable photos of BOTH PCB
   sides/chip markings or its product documentation. Confirm the MCU and any
   external flash; do not infer them from the case or connectors.
2. Establish the documented BOOTSEL/debug recovery procedure and read-only
   firmware backup method. Verify backup size/hash and preserve it privately
   before any flash write. Do not guess button combinations or use Pico UF2.
3. Map phone-side D+/D-, VBUS protection/switch, LEDs and buttons from a
   schematic or electrical measurements. A working proprietary PWN firmware
   does not establish that its data routing matches usbliter8 GP12/13.
4. Implement that board's USB adapter, a board-specific SDK configuration and
   a new flash layout. Link the decoder/source and immutable compressed stage,
   retaining expected-device binding. Measure complete ARM flash and RAM use;
   reject anything beyond confirmed capacity. No image is currently produced.
5. Verify the original firmware recovery path, then conduct separate USB
   enumeration, DFU upload and Recovery tests with logs. Only after those pass
   attempt the existing Preboot/DataB handoff. That handoff remains physically
   unverified even on the genuine Pico 2.

Do not reinstall DataB, update/erase stock iOS, change NVRAM/APFS roles, stage
Preboot automatically or overwrite the working service-board firmware.
