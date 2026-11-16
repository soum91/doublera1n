#include "boot_plan.h"
#include <string.h>

static uint32_t read_u32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint64_t read_u64(const unsigned char *p) {
    return (uint64_t)read_u32(p) | ((uint64_t)read_u32(p + 4) << 32);
}
static int get(const struct dbp_reader *r, uint64_t off, void *dest, size_t len) {
    if (!r || !r->read_at || off > r->size || len > r->size - off)
        return DBP_ERR_READ;
    return r->read_at(r->ctx, off, dest, len) ? DBP_ERR_READ : 0;
}
static int decode_str(char *out, size_t outlen, const unsigned char *s, size_t n) {
    size_t i;
    if (n + 1 > outlen) return DBP_ERR_FORMAT;
    for (i = 0; i < n && s[i]; ++i) {
        if (s[i] < 32 || s[i] > 126) return DBP_ERR_FORMAT;
        out[i] = (char)s[i];
    }
    if (i == n) return DBP_ERR_FORMAT; /* require NUL terminator */
    out[i] = 0;
    for (; i < n; ++i) if (s[i]) return DBP_ERR_FORMAT;
    return 0;
}
static int valid_action(const struct dbp_stage *e, unsigned index, unsigned count) {
    if (index == 0) return !strcmp(e->action, "dfu_boot") && !strcmp(e->name, "iBSS.raw");
    if (index == 1) return !strcmp(e->action, "ibec") && !strcmp(e->name, "iBEC.img4");
    if (index == 2) return !strcmp(e->action, "go") && !e->name[0];
    if (index == count - 1) return !strcmp(e->action, "bootx") && !e->name[0];
    return !strcmp(e->action, "firmware") || !strcmp(e->action, "ramdisk") ||
           !strcmp(e->action, "devicetree") || !strcmp(e->action, "rsepfirmware") ||
           !strcmp(e->action, "kernel");
}
static int check_stage_names(const struct dbp_plan *plan) {
    const char *names[] = {"ANE.img4", "AOP.img4", "AVE.img4", "SPTM.img4",
        "TXM.img4", "GFX.img4", "ISP.img4", "PMP.img4", "RestoreTrustCache.img4",
        "SIO.img4", "WCH.img4", "RestoreRamdisk.img4", "DeviceTree.img4",
        "SEP.img4", "Kernelcache.img4"};
    const char *actions[] = {"firmware", "firmware", "firmware", "firmware",
        "firmware", "firmware", "firmware", "firmware", "firmware",
        "firmware", "firmware", "ramdisk", "devicetree", "rsepfirmware", "kernel"};
    unsigned k = 3;
    for (unsigned i = 0; i < sizeof(names)/sizeof(names[0]); i++) {
        if (i == 10 && (k >= plan->count || strcmp(plan->stages[k].name, "WCH.img4")))
            continue; /* optional wireless charging firmware */
        if (k >= plan->count || strcmp(plan->stages[k].name, names[i]) ||
            strcmp(plan->stages[k].action, actions[i])) return DBP_ERR_FORMAT;
        ++k;
    }
    return k == plan->count - 1 ? 0 : DBP_ERR_FORMAT;
}
int dbp_parse(const struct dbp_reader *reader, struct dbp_plan *out) {
    unsigned char head[DBP_HEADER_SIZE], b[DBP_ENTRY_SIZE];
    if (!reader || !out) return DBP_ERR_FORMAT;
    memset(out, 0, sizeof(*out));
    if (get(reader, 0, head, sizeof(head))) return DBP_ERR_READ;
    if (memcmp(head, "DBPICO01", 8) || read_u32(head + 8) != 1) return DBP_ERR_MAGIC;
    out->count = read_u32(head + 12);
    if (out->count < 5 || out->count > DBP_MAX_STAGES || read_u64(head + 48) != reader->size)
        return DBP_ERR_FORMAT;
    if (decode_str(out->board, sizeof(out->board), head + 16, 16) ||
        decode_str(out->build, sizeof(out->build), head + 32, 16)) return DBP_ERR_FORMAT;
    /* Current installed target only. Never accidentally replay images from another board/build. */
    if (strcmp(out->board, "d431ap") || strcmp(out->build, "24A446")) return DBP_ERR_FORMAT;
    uint64_t data_start = (DBP_HEADER_SIZE + out->count * DBP_ENTRY_SIZE + 511u) & ~(uint64_t)511u;
    for (unsigned i = 0; i < out->count; i++) {
        if (get(reader, DBP_HEADER_SIZE + i * DBP_ENTRY_SIZE, b, sizeof(b))) return DBP_ERR_READ;
        struct dbp_stage *e = &out->stages[i];
        if (decode_str(e->name, sizeof(e->name), b, 32) ||
            decode_str(e->action, sizeof(e->action), b + 32, 16)) return DBP_ERR_FORMAT;
        e->offset = read_u64(b + 48);
        e->size = read_u64(b + 56);
        e->delay_ms = read_u32(b + 64);
        e->crc32 = read_u32(b + 68);
        memcpy(e->sha256, b + 72, 32);
        if (!valid_action(e, i, out->count)) return DBP_ERR_FORMAT;
        if (!e->name[0]) {
            if (e->offset || e->size || e->crc32) return DBP_ERR_FORMAT;
        } else if (!e->size || e->offset < data_start || e->offset % 512 ||
                   e->offset > reader->size || e->size > reader->size - e->offset) return DBP_ERR_FORMAT;
        for (unsigned j = 0; j < i; j++) {
            const struct dbp_stage *prev = &out->stages[j];
            if (e->size && prev->size &&
                e->offset < prev->offset + prev->size &&
                prev->offset < e->offset + e->size) return DBP_ERR_FORMAT;
        }
    }
    /* Exact image sequence from lib/boot_chain.py --osbjb, WCH optional. */
    return check_stage_names(out);
}
static uint32_t step_crc(uint32_t crc, const unsigned char *buf, size_t len) {
    for (size_t i = 0; i < len; ++i) {
        crc ^= buf[i];
        for (unsigned n = 0; n < 8; ++n) crc = (crc >> 1) ^ (0xEDB88320u & -(int32_t)(crc & 1));
    }
    return crc;
}
int dbp_verify(const struct dbp_reader *reader, const struct dbp_plan *plan) {
    unsigned char b[DBP_IO_SIZE];
    if (!reader || !plan) return DBP_ERR_FORMAT;
    for (unsigned i = 0; i < plan->count; ++i) {
        const struct dbp_stage *e = &plan->stages[i];
        if (!e->size) continue;
        uint64_t remain = e->size, off = e->offset;
        uint32_t crc = 0xFFFFFFFFu;
        while (remain) {
            size_t n = remain < sizeof(b) ? (size_t)remain : sizeof(b);
            if (get(reader, off, b, n)) return DBP_ERR_READ;
            crc = step_crc(crc, b, n);
            off += n;
            remain -= n;
        }
        if ((crc ^ 0xFFFFFFFFu) != e->crc32) return DBP_ERR_CRC;
    }
    return 0;
}
int dbp_replay_verified(const struct dbp_reader *reader,
                        const struct dbp_plan *plan,
                        const struct dbp_transport *t) {
    int rc;
    if (!t || !t->execute || !reader || !plan) return DBP_ERR_FORMAT;
    if ((rc = dbp_verify(reader, plan)) != 0) return rc;
    for (unsigned i = 0; i < plan->count; i++) {
        const struct dbp_stage *s = &plan->stages[i];
        if (t->execute(t->ctx, reader, s)) return DBP_ERR_TRANSPORT;
        if (s->delay_ms && t->delay_ms) t->delay_ms(t->ctx, s->delay_ms);
    }
    return 0;
}
