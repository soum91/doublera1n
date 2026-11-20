/* DBZBLK01 block reader. Portable implementation; NOT a board firmware. */
#include "block_source.h"
#include <string.h>

static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
int dbnand_block_init(struct dbnand_block_source *s, const uint8_t *p, size_t n) {
    if (!s) return -1;
    memset(s, 0, sizeof(*s));
    if (!p || n < 32 || memcmp(p, "DBZBLK01", 8) || le32(p+8) != 1 ||
        le32(p+16) != DBNAND_BLOCK_BYTES || le32(p+28)) return -1;
    uint32_t bytes = le32(p+12), count = le32(p+20);
    if (!bytes || bytes > 2842448u || count != (bytes+32767u)/32768u) return -1;
    size_t offset = 32;
    uint32_t total = 0;
    for (uint32_t i = 0; i < count; ++i) {
        if (n-offset < 12) return -1;
        uint32_t flags = le32(p+offset), stored = flags & 0x7fffffffu;
        uint32_t out = le32(p+offset+4), expected = bytes-total;
        if (expected > DBNAND_BLOCK_BYTES) expected = DBNAND_BLOCK_BYTES;
        offset += 12;
        if (!stored || stored > DBNAND_BLOCK_BYTES || out != expected ||
            stored > n-offset || ((flags & 0x80000000u) && stored != out)) return -1;
        offset += stored; total += out;
    }
    if (offset != n || total != bytes) return -1;
    s->packed = p; s->packed_bytes = n; s->next_record = 32;
    s->bytes = bytes; s->crc32 = le32(p+24); s->count = count;
    return 0;
}
static int load_block(struct dbnand_block_source *s) {
    size_t offset = s->next_record;
    if (s->loaded >= s->count || offset > s->packed_bytes || s->packed_bytes-offset < 12) return -1;
    const uint8_t *p = s->packed+offset;
    uint32_t flags = le32(p), stored = flags & 0x7fffffffu;
    uint32_t out = le32(p+4), crc = le32(p+8);
    offset += 12;
    if (!stored || stored > DBNAND_BLOCK_BYTES || !out || out > DBNAND_BLOCK_BYTES ||
        stored > s->packed_bytes-offset) return -1;
    if (flags & 0x80000000u) {
        if (stored != out) return -1;
        memcpy(s->decoded, s->packed+offset, out);
    } else {
        size_t in_bytes = stored, out_bytes = out;
        tinfl_init(&s->inflater);
        tinfl_status status = tinfl_decompress(&s->inflater, s->packed+offset,
            &in_bytes, s->decoded, s->decoded, &out_bytes,
            TINFL_FLAG_PARSE_ZLIB_HEADER | TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF);
        if (status != TINFL_STATUS_DONE || in_bytes != stored || out_bytes != out) return -1;
    }
    if (dbnand_crc32(s->decoded, out) != crc) return -1;
    s->next_record = offset+stored; ++s->loaded; s->cached_bytes = out;
    return 0;
}
int dbnand_block_read(void *ctx, size_t offset, uint8_t *dest, size_t n) {
    struct dbnand_block_source *s = ctx;
    if (!s || !s->packed || !dest || !n || offset > s->bytes || n > s->bytes-offset) return -1;
    if (!offset) {
        s->position = 0; s->loaded = 0; s->cached_bytes = 0; s->next_record = 32;
    }
    if (offset != s->position) return -1;
    while (n) {
        size_t within = s->position % DBNAND_BLOCK_BYTES;
        if (!s->cached_bytes || within == 0) {
            if (load_block(s)) return -1;
        }
        if (within >= s->cached_bytes) return -1;
        size_t take = s->cached_bytes-within;
        if (take > n) take = n;
        memcpy(dest, s->decoded+within, take);
        s->position += take; dest += take; n -= take;
    }
    return 0;
}
