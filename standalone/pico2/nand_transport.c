#include "nand_transport.h"
#include <string.h>

static uint32_t crc_update(uint32_t crc, const uint8_t *data, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        crc ^= data[i];
        for (unsigned j = 0; j < 8; ++j)
            crc = (crc >> 1) ^ ((0u - (crc & 1u)) & 0xedb88320u);
    }
    return crc;
}
uint32_t dbnand_crc32(const uint8_t *data, size_t n) {
    return ~crc_update(0xffffffffu, data, n);
}
static int hex_field(const char *s, const char *key, unsigned max_digits, uint64_t *out) {
    const char *p = strstr(s, key);
    if (!p || (p != s && p[-1] != ' ')) return -1;
    p += strlen(key);
    uint64_t value = 0;
    unsigned n = 0;
    while (*p && *p != ' ') {
        unsigned c = (unsigned char)*p++, digit;
        if (c >= '0' && c <= '9') digit = c - '0';
        else if (c >= 'A' && c <= 'F') digit = c - 'A' + 10;
        else if (c >= 'a' && c <= 'f') digit = c - 'a' + 10;
        else return -1;
        if (++n > max_digits) return -1;
        value = (value << 4) | digit;
    }
    if (!n) return -1;
    *out = value;
    return 0;
}
int dbnand_parse_serial(const char *data, size_t capacity, struct dbnand_identity *id) {
    if (!data || !id || !capacity || capacity > 256 || !memchr(data, 0, capacity)) return -1;
    uint64_t cpid, bdid, ecid;
    if (hex_field(data, "CPID:", 4, &cpid) || hex_field(data, "BDID:", 4, &bdid) ||
        hex_field(data, "ECID:", 16, &ecid) || !ecid) return -1;
    id->cpid = (uint16_t)cpid; id->bdid = (uint16_t)bdid; id->ecid = ecid;
    id->pwned = strstr(data, "PWND:") != NULL && strstr(data, "usbliter8") != NULL;
    return 0;
}
static int matching(const struct dbnand_identity *id, uint64_t ecid, int recovery) {
    if (id->vendor != 0x05ac || id->cpid != 0x8030 || id->bdid != 2 || id->ecid != ecid) return 0;
    return recovery ? (id->product >= 0x1280 && id->product <= 0x1283) :
                      (id->product == 0x1227 && id->pwned);
}
int dbnand_run_source(const struct dbnand_io *io, const struct dbnand_source *source,
                     size_t bytes, uint32_t crc, uint64_t ecid) {
    if (!io || !io->identity || !io->enumerate || !io->control || !io->wait_recovery ||
        !source || !source->read || bytes != 2842448u || !ecid)
        return DBNAND_ERR_IMAGE;
    uint8_t buffer[192];
    uint32_t actual = 0xffffffffu;
    /* Decode/validate the entire image before the first USB action. */
    for (size_t offset = 0; offset < bytes; offset += sizeof(buffer)) {
        size_t n = bytes - offset;
        if (n > sizeof(buffer)) n = sizeof(buffer);
        if (source->read(source->ctx, offset, buffer, n)) return DBNAND_ERR_IMAGE;
        actual = crc_update(actual, buffer, n);
    }
    if (~actual != crc) return DBNAND_ERR_IMAGE;
    struct dbnand_identity id = {0};
    if (io->identity(io->ctx, &id) || !matching(&id, ecid, 0)) return DBNAND_ERR_IDENTITY;
    if (io->enumerate(io->ctx)) return DBNAND_ERR_ENUMERATION;
    actual = 0xffffffffu;
    for (size_t offset = 0; offset < bytes; offset += 192u) {
        size_t n = bytes - offset;
        if (n > 192u) n = 192u; /* upstream PIO EP0 length is uint8_t */
        if (source->read(source->ctx, offset, buffer, n)) return DBNAND_ERR_IMAGE;
        actual = crc_update(actual, buffer, n);
        if (io->control(io->ctx, 0x21, 1, buffer, (uint16_t)n, 1000)) return DBNAND_ERR_DFU;
    }
    /* A source changing during upload must never trigger CUSTOM_BOOT. */
    if (~actual != crc) return DBNAND_ERR_IMAGE;
    if (io->control(io->ctx, 0x21, 1, NULL, 0, 100) ||
        io->control(io->ctx, 0x21, 8, NULL, 0, 100)) return DBNAND_ERR_DFU;
    /* A disconnect on ABORT after CUSTOM_BOOT is expected. */
    (void)io->control(io->ctx, 0x21, 4, NULL, 0, 100);
    if (io->wait_recovery(io->ctx, 90000)) return DBNAND_ERR_RECOVERY;
    memset(&id, 0, sizeof(id));
    if (io->identity(io->ctx, &id) || !matching(&id, ecid, 1)) return DBNAND_ERR_IDENTITY;
    if (io->enumerate(io->ctx)) return DBNAND_ERR_ENUMERATION;
    static const uint8_t command[] = "memboot";
    if (io->control(io->ctx, 0x40, 0, command, sizeof(command), 1000)) return DBNAND_ERR_COMMAND;
    return DBNAND_HANDED_OFF;
}
static int memory_read(void *ctx, size_t offset, uint8_t *destination, size_t n) {
    memcpy(destination, (const uint8_t *)ctx + offset, n);
    return 0;
}
int dbnand_run(const struct dbnand_io *io, const uint8_t *image, size_t bytes,
               uint32_t crc, uint64_t ecid) {
    if (!image) return DBNAND_ERR_IMAGE;
    const struct dbnand_source source = {(void *)image, memory_read};
    return dbnand_run_source(io, &source, bytes, crc, ecid);
}
