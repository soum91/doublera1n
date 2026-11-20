#ifndef DBNAND_BLOCK_SOURCE_H
#define DBNAND_BLOCK_SOURCE_H
#include "nand_transport.h"
#include "block_miniz.h"
#define DBNAND_BLOCK_BYTES 32768u
/* Caller-owned state: no heap, one output block and inflater state. Keep the
 * entire object out of small stacks. Input must remain immutable for both
 * validation and upload passes. No board or USB functions are called here. */
struct dbnand_block_source {
    const uint8_t *packed;
    size_t packed_bytes, next_record, position;
    uint32_t bytes, crc32, count, loaded, cached_bytes;
    tinfl_decompressor inflater;
    uint8_t decoded[DBNAND_BLOCK_BYTES];
};
int dbnand_block_init(struct dbnand_block_source *, const uint8_t *, size_t);
int dbnand_block_read(void *, size_t, uint8_t *, size_t);
#endif
