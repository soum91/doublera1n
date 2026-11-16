#ifndef DBNAND_USBLITER8_ADAPTER_H
#define DBNAND_USBLITER8_ADAPTER_H
#include <stddef.h>
#include <stdint.h>
int dbnand_pico_boot(const uint8_t *image, size_t bytes, uint32_t crc32, uint64_t ecid);
#endif
