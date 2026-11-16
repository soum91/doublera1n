#ifndef DOUBLERA1N_PICO2_BOOT_PLAN_H
#define DOUBLERA1N_PICO2_BOOT_PLAN_H
#include <stddef.h>
#include <stdint.h>

/* Format v1: little-endian on storage; do not cast packed byte buffers. */
#define DBP_HEADER_SIZE 56u
#define DBP_ENTRY_SIZE 104u
#define DBP_MAX_STAGES 64u
#define DBP_IO_SIZE 512u
#define DBP_ERR_MAGIC -1
#define DBP_ERR_READ -2
#define DBP_ERR_FORMAT -3
#define DBP_ERR_CRC -4
#define DBP_ERR_TRANSPORT -5

struct dbp_reader {
    void *ctx;
    int (*read_at)(void *ctx, uint64_t offset, void *dst, size_t len);
    uint64_t size;
};

struct dbp_stage {
    char name[33];
    char action[17];
    uint64_t offset;
    uint64_t size;
    uint32_t delay_ms;
    uint32_t crc32;
    uint8_t sha256[32];
};

struct dbp_plan {
    char board[17];
    char build[17];
    unsigned count;
    struct dbp_stage stages[DBP_MAX_STAGES];
};

/* Only loads the plan and checks layout/order. No phone interaction. */
int dbp_parse(const struct dbp_reader *reader, struct dbp_plan *out);

/* Reads all images with a 512-byte buffer; checks CRC32 before any USB writes. */
int dbp_verify(const struct dbp_reader *reader, const struct dbp_plan *plan);

/* USB transport runs only after successful parse + verify; zero means success. */
struct dbp_transport {
    void *ctx;
    /* Each stage action: dfu_boot, ibec, go, firmware, ramdisk,
       devicetree, rsepfirmware, kernel, bootx. USB adapter must implement
       DFU<->Recovery re-enumeration, image chunking and status handshakes. */
    int (*execute)(void *ctx, const struct dbp_reader *, const struct dbp_stage *);
    void (*delay_ms)(void *ctx, uint32_t);
};
int dbp_replay_verified(const struct dbp_reader *reader,
                        const struct dbp_plan *plan,
                        const struct dbp_transport *transport);
#endif
