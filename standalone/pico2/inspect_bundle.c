/* Portable offline verifier. Build: cc -std=c11 -Wall -Wextra -Werror
   -o inspect_bundle inspect_bundle.c boot_plan.c */
#include "boot_plan.h"
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

struct filectx { FILE *f; };
static int read_at(void *p, uint64_t off, void *dst, size_t len) {
    struct filectx *f = p;
    if (off > (uint64_t)0x7fffffffL * 4096u) return -1;
    if (fseek(f->f, (long)off, SEEK_SET)) return -1;
    return fread(dst, 1, len, f->f) != len;
}
int main(int argc, char **argv) {
    if (argc != 2) { fprintf(stderr, "Usage: %s BOOT.BIN\n", argv[0]); return 2; }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 2; }
    if (fseek(f, 0, SEEK_END)) { fclose(f); return 2; }
    long n = ftell(f);
    if (n < 0) { fclose(f); return 2; }
    struct filectx context = { f };
    struct dbp_reader reader = { &context, read_at, (uint64_t)n };
    struct dbp_plan *plan = calloc(1, sizeof(*plan));
    if (!plan) { fclose(f); return 2; }
    int rc = dbp_parse(&reader, plan);
    if (!rc) rc = dbp_verify(&reader, plan);
    if (!rc) {
        printf("Boot bundle verified: %s %s; %u stages; %ld bytes\n",
            plan->board, plan->build, plan->count, n);
        for (unsigned i = 0; i < plan->count; ++i)
            printf("%2u  %-18s %-28s %llu bytes\n", i, plan->stages[i].action,
                plan->stages[i].name, (unsigned long long)plan->stages[i].size);
    } else fprintf(stderr, "Boot bundle REJECTED, error %d\n", rc);
    free(plan);
    fclose(f);
    return rc ? 1 : 0;
}
