/* Own adapter to upstream bus.h/usb.h APIs; no upstream exploit code vendored.
 * Call on the coordinator core after the exploit succeeds. Device-untested. */
#include "nand_transport.h"
#include "nand_usbliter8_adapter.h"
#include <string.h>
#include <stdbool.h>
#include "pico/stdlib.h"
#include "bus.h"
#include "usb.h"
struct req { uint8_t type, request; uint16_t value, index, length; } __attribute__((packed));
struct ctl { uint8_t type, request; const uint8_t *data; uint16_t length; uint32_t timeout; };
/* Each bus operation has its own protocol timeout. Wait for callback completion
 * so a FIFO timeout cannot leave core 1 using an expired stack context. */
static uint8_t tx[192];
static int ctl_on_bus(bus_t *bus, void *opaque) {
    struct ctl *c = opaque;
    if (c->length > sizeof(tx)) return -1;
    struct req r = {c->type, c->request, 0, 0, c->length};
    if (c->length) memcpy(tx, c->data, c->length);
    return bus_control_xfer(bus, (uint8_t *)&r, c->length ? tx : NULL,
                            (uint8_t)c->length, false, c->timeout);
}
static int control(void *ctx, uint8_t type, uint8_t request, const uint8_t *p, uint16_t n, uint32_t timeout) {
    (void)ctx;
    struct ctl c = {type, request, p, n, timeout};
    return usb_bus_execute(ctl_on_bus, &c, 0);
}
static int enumerate_on_bus(bus_t *bus, void *ctx) {
    (void)ctx;
    struct req address = {0, 5, 1, 0, 0}, config = {0, 9, 1, 0, 0};
    if (bus_control_xfer(bus, (uint8_t *)&address, NULL, 0, false, 100)) return -1;
    sleep_ms(10);
    bus_close_all(bus); bus->dev->address = 1;
    if (!bus_open_ep0(bus, 64)) return -1;
    return bus_control_xfer(bus, (uint8_t *)&config, NULL, 0, false, 100);
}
static int enumerate(void *ctx) {
    (void)ctx;
    return usb_bus_execute(enumerate_on_bus, NULL, 0);
}
static int identity_on_bus(bus_t *bus, void *opaque) {
    struct dbnand_identity *id = opaque;
    uint8_t device[18] = {0}, language[4] = {0}, serial[254] = {0};
    struct req r = {0x80, 6, 0x100, 0, sizeof(device)};
    if (bus_control_xfer(bus, (uint8_t *)&r, device, sizeof(device), true, 1000) || device[0] != 18 || device[1] != 1)
        return -1;
    id->vendor = (uint16_t)(device[8] | device[9] << 8);
    id->product = (uint16_t)(device[10] | device[11] << 8);
    if (id->vendor != 0x05ac || !device[16]) return -1;
    r.value = 0x300; r.length = sizeof(language);
    if (bus_control_xfer(bus, (uint8_t *)&r, language, sizeof(language), true, 1000) || language[0] < 4 || language[1] != 3)
        return -1;
    r.value = (uint16_t)(0x300 | device[16]); r.index = (uint16_t)(language[2] | language[3] << 8);
    r.length = sizeof(serial);
    if (bus_control_xfer(bus, (uint8_t *)&r, serial, sizeof(serial), true, 1000) ||
        serial[0] < 2 || serial[0] > sizeof(serial) || serial[0] % 2 || serial[1] != 3) return -1;
    char ascii[128] = {0};
    unsigned chars = (serial[0] - 2u) / 2u;
    for (unsigned i = 0; i < chars; ++i) {
        if (serial[3 + i*2] || serial[2 + i*2] > 127 || !serial[2 + i*2]) return -1;
        ascii[i] = (char)serial[2 + i*2];
    }
    return dbnand_parse_serial(ascii, sizeof(ascii), id);
}
static int identity(void *ctx, struct dbnand_identity *id) {
    (void)ctx;
    return usb_bus_execute(identity_on_bus, id, 0);
}
static int reset_on_bus(bus_t *bus, void *ctx) {
    (void)ctx;
    bus_reset_ep0_reopen(bus);
    return 0;
}
static int wait_recovery(void *ctx, uint32_t timeout_ms) {
    (void)ctx;
    /* Give raw iBoot time to leave DFU, then reset the bus. Retry the
       initial reset a few times: the phone may need longer to re-enumerate
       after exploitation, and a single bus-reset failure is not fatal. */
    sleep_ms(2000);
    int reset_ok = 0;
    for (unsigned attempt = 0; attempt < 3 && !reset_ok; ++attempt) {
        if (!usb_bus_execute(reset_on_bus, NULL, 0)) reset_ok = 1;
        else sleep_ms(500);
    }
    if (!reset_ok) return -1;
    for (uint32_t elapsed = 2000; elapsed < timeout_ms; elapsed += 500) {
        struct dbnand_identity id = {0};
        if (!identity(NULL, &id) && id.product >= 0x1280 && id.product <= 0x1283) return 0;
        sleep_ms(500);
    }
    return -1;
}
int dbnand_pico_boot(const uint8_t *image, size_t bytes, uint32_t crc32, uint64_t ecid) {
    const struct dbnand_io io = {NULL, identity, enumerate, control, wait_recovery};
    return dbnand_run(&io, image, bytes, crc32, ecid);
}
