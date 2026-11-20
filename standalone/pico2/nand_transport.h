#ifndef DBNAND_TRANSPORT_H
#define DBNAND_TRANSPORT_H
#include <stddef.h>
#include <stdint.h>

struct dbnand_identity {
    uint16_t vendor, product, cpid, bdid;
    uint64_t ecid;
    int pwned;
};
struct dbnand_io {
    void *ctx;
    int (*identity)(void *, struct dbnand_identity *);
    int (*enumerate)(void *);
    int (*control)(void *, uint8_t type, uint8_t request, const uint8_t *, uint16_t, uint32_t timeout_ms);
    int (*wait_recovery)(void *, uint32_t timeout_ms);
};
enum { DBNAND_HANDED_OFF = 1, DBNAND_ERR_IMAGE = -1,
       DBNAND_ERR_IDENTITY = -2, DBNAND_ERR_ENUMERATION = -3,
       DBNAND_ERR_DFU = -4, DBNAND_ERR_RECOVERY = -5, DBNAND_ERR_COMMAND = -6 };
uint32_t dbnand_crc32(const uint8_t *, size_t);
/* Immutable, replayable source. read returns 0 only after filling all n bytes.
 * Calls are sequential in each of two passes, restarting at offset 0. A block
 * decoder may rewind there; it must validate block integrity before returning.
 * No embedded decompressor or board-specific USB port is provided here. */
struct dbnand_source {
    void *ctx;
    int (*read)(void *, size_t offset, uint8_t *destination, size_t n);
};
int dbnand_run_source(const struct dbnand_io *, const struct dbnand_source *,
                     size_t bytes, uint32_t expected_crc32, uint64_t expected_ecid);
/* Parse only a bounded, ASCII Apple serial; rejects missing/overflowing fields. */
int dbnand_parse_serial(const char *, size_t, struct dbnand_identity *);
/* EP0-only: verified image -> DFU -> Recovery -> memboot. Positive result means
 * command handoff only, NEVER proof that a kernel or jailbreak booted. */
int dbnand_run(const struct dbnand_io *, const uint8_t *image, size_t bytes,
               uint32_t expected_crc32, uint64_t expected_ecid);
#endif
